#!/usr/bin/env python3
"""Low-footprint local pass-through proxy for the DeepSeek Responses API.

Fixes DeepSeek forcing thinking mode on for Codex-identified clients: rewrites
the User-Agent to a generic one and strips codex-specific headers so the server
honors ``reasoning.effort`` from the request body (e.g. effort=none -> no CoT).

Runs on a single ``asyncio`` event loop (no per-request threads) to keep idle
CPU ~0 and RSS low, so it's cheap to keep resident via launchd.

Usage: python3 ds-proxy.py [--port 19100] [--upstream https://api.deepseek.com]
"""

import argparse
import asyncio
import json
import os
import re
import signal
import ssl
from urllib import request


# Header names that identify the request as coming from the Codex client; the
# server forces reasoning on if any of them is present, so strip all of them.
STRIP_HEADER_EXACT = {"originator", "session-id", "thread-id", "user-agent", "host", "content-length", "connection"}


def _header_value(headers_raw: list, name: str) -> str | None:
    """Case-insensitive header lookup (urllib sends `Content-Length`, not `content-length`)."""
    for k, v in headers_raw:
        if k.lower() == name:
            return v
    return None


# Catalog-only model slugs used by the Codex UI -> real upstream model names.
# Requests still arrive with the UI slug in body["model"]; rewrite before relay.
# Override with repeated --model-map slug=upstream arguments.
DEFAULT_MODEL_MAP = {
    "gpt-5.2": "deepseek-v4-flash",
}


def _parse_model_map(pairs: list[str]) -> dict[str, str]:
    """Parse repeated --model-map slug=upstream arguments into a dict."""
    out = dict(DEFAULT_MODEL_MAP)
    for pair in pairs or []:
        if "=" not in pair:
            raise SystemExit("--model-map expects slug=upstream, got: %r" % pair)
        k, _, v = pair.partition("=")
        out[k.strip()] = v.strip()
    return out


# data-url sha256 -> glance description; avoids re-describing the same image
# when the model repeats it in later turns of the same conversation.
_GLANCE_CACHE: dict[str, str] = {}


def _load_env_file(path: str | None) -> None:
    """Minimal .env loader; values already in the environment win."""
    if not path or not os.path.isfile(path):
        return
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as e:
        _log("[ua-proxy] env file load failed: %r" % e)


def _vision_api_key() -> str:
    return (os.environ.get("VISION_API_KEY") or os.environ.get("GLANCE_API_KEY")
            or os.environ.get("GEMINI_API_KEY") or "").strip()


def _describe_image_with_api(data_url: str, api_key: str) -> str | None:
    """Describe an image via an OpenAI-compatible vision API (no extra installs)."""
    base_url = os.environ.get("VISION_BASE_URL", "https://api.inferera.com/v1").rstrip("/")
    model = os.environ.get("VISION_MODEL", "gemini-3.6-flash")
    payload = {
        "model": model,
        "max_tokens": 1024,
        "reasoning_effort": "none",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "请详细描述这张图片中的内容。"},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
    }
    req = request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key},
    )
    try:
        with request.urlopen(req, timeout=180) as r:
            d = json.load(r)
        return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        _log("[ua-proxy] vision api failed: %r" % e)
        return None


def _describe_image_with_cli(data_url: str, glance_cmd: list[str]) -> str | None:
    """Decode a data URL image and describe it with a local CLI (glance or equivalent)."""
    import base64
    import subprocess
    import tempfile

    m = re.match(r"^data:[^,]*;base64,(.+)$", data_url, re.S)
    if not m:
        return None
    raw = base64.b64decode(m.group(1))
    if raw[:4] == b"\x89PNG":
        ext = "png"
    elif raw[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        ext = "webp"
    elif raw[:6] in (b"GIF87a", b"GIF89a"):
        ext = "gif"
    else:
        ext = "png"
    fd, tmp = tempfile.mkstemp(suffix="." + ext)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
    try:
        res = subprocess.run(
            glance_cmd + [tmp],
            capture_output=True, text=True, timeout=90,
        )
        desc = (res.stdout or res.stderr or "").strip()
        if res.returncode != 0:
            # 失败信息（如视觉上游 429）不缓存：限流恢复后重试同一张图会重新描述。
            _log("[ua-proxy] glance cli failed rc=%d: %s"
                 % (res.returncode, desc[:200]))
        return desc or None
    finally:
        os.unlink(tmp)


def _looks_like_error(text: str) -> bool:
    """True for upstream failure texts that must not be cached as descriptions."""
    return text.startswith("请求失败") or '{"error"' in text


def _image_desc_from_data_url(data_url: str, glance_cmd: list[str]) -> str | None:
    """Describe a data URL image: built-in vision API first, local CLI as fallback."""
    import hashlib

    try:
        cache_key = hashlib.sha256(data_url.encode()).hexdigest()
        if cache_key in _GLANCE_CACHE:
            return _GLANCE_CACHE[cache_key]
        api_key = _vision_api_key()
        desc = _describe_image_with_api(data_url, api_key) if api_key else None
        if not desc:
            desc = _describe_image_with_cli(data_url, glance_cmd)
        if desc and not _looks_like_error(desc):
            _GLANCE_CACHE[cache_key] = desc
        return desc
    except Exception as e:
        _log("[ua-proxy] image describe failed: %r" % e)
        return None


async def _rewrite_image_inputs(parsed: dict, glance_cmd: list[str]) -> bool:
    """Replace input_image entries with text descriptions. Returns True if any replaced.

    Images can arrive in two shapes:
      - message.content: [{type: input_image, ...}] (pasted images)
      - function_call_output.output: [{type: input_image, ...}] (view_image results)
    Both are rewritten so the upstream model receives readable text.

    Multiple images in one request are described concurrently (async to_thread),
    so N images cost ~1 vision call instead of N serialized ones.
    """
    inp = parsed.get("input")
    if not isinstance(inp, list):
        return False
    jobs = []  # (item, field, list_index, data_url)
    for item in inp:
        if not isinstance(item, dict):
            continue
        for field in ("content", "output"):
            lst = item.get(field)
            if not isinstance(lst, list):
                continue
            for idx, c in enumerate(lst):
                if isinstance(c, dict) and c.get("type") == "input_image":
                    url = c.get("image_url")
                    if isinstance(url, str) and url.startswith("data:"):
                        jobs.append((item, field, idx, url))
    if not jobs:
        return False
    # 同一请求内同图只描述一次
    urls = []
    for _, _, _, url in jobs:
        if url not in urls:
            urls.append(url)

    async def describe(url: str) -> tuple[str, str | None]:
        desc = await asyncio.to_thread(_image_desc_from_data_url, url, glance_cmd)
        if desc:
            _log(
                "[ua-proxy] image -> glance (desc_len=%d, cache=%d)"
                % (len(desc), len(_GLANCE_CACHE))
            )
        return url, desc

    results = dict(await asyncio.gather(*(describe(u) for u in urls)))
    replaced = False
    for item, field, idx, url in jobs:
        desc = results.get(url)
        if not desc:
            continue
        item[field][idx] = {
            "type": "input_text",
            "text": "[local vision model description] " + desc,
        }
        replaced = True
    return replaced


def _inject_reasoning_summaries(sse_text: str) -> str:
    """DeepSeek never emits reasoning summary events (summary always []), so the Codex
    frontend renders an empty thinking block ("thinking ..."). Inject the raw reasoning
    text as an OpenAI-style summary so the UI has content to show.
    """
    blocks = sse_text.split("\n\n")
    parsed: list[tuple[str | None, dict | None, str]] = []
    items: dict[str, dict] = {}
    for blk in blocks:
        ev = None
        data = None
        for line in blk.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = line[5:].strip()
        obj = None
        if data:
            try:
                obj = json.loads(data)
            except Exception:
                obj = None
        parsed.append((ev, obj, blk))
        if not obj:
            continue
        t = obj.get("type")
        if t == "response.output_item.added":
            it = obj.get("item") or {}
            if it.get("type") == "reasoning":
                items[it.get("id")] = {
                    "text": "",
                    "output_index": obj.get("output_index", 0),
                }
        elif t == "response.reasoning_text.delta":
            info = items.get(obj.get("item_id"))
            if info:
                info["text"] += obj.get("delta", "")
        elif t == "response.reasoning_text.done":
            info = items.get(obj.get("item_id"))
            if info:
                info["text"] = obj.get("text", info["text"])

    def summary_blocks(item_id: str, output_index: int, text: str) -> str:
        part = {
            "type": "response.reasoning_summary_part.added",
            "item_id": item_id,
            "output_index": output_index,
            "summary_index": 0,
            "part": {"type": "reasoning_summary", "text": ""},
            "sequence_number": 0,
        }
        delta = {
            "type": "response.reasoning_summary_text.delta",
            "item_id": item_id,
            "output_index": output_index,
            "summary_index": 0,
            "delta": text,
            "sequence_number": 0,
        }
        return (
            "event: response.reasoning_summary_part.added\ndata: "
            + json.dumps(part, ensure_ascii=False)
            + "\n\nevent: response.reasoning_summary_text.delta\ndata: "
            + json.dumps(delta, ensure_ascii=False)
            + "\n\n"
        )

    injected = 0
    out_blocks: list[str] = []
    for ev, obj, blk in parsed:
        if obj and obj.get("type") == "response.output_item.done":
            it = obj.get("item") or {}
            if it.get("type") == "reasoning":
                info = items.get(it.get("id"))
                if info and info["text"]:
                    fixed = json.loads(json.dumps(obj))
                    fixed["item"]["summary"] = [
                        {"type": "summary_text", "text": info["text"]}
                    ]
                    blk = "event: response.output_item.done\ndata: " + json.dumps(
                        fixed, ensure_ascii=False
                    )
        out_blocks.append(blk)
        if obj and obj.get("type") == "response.output_item.added":
            it = obj.get("item") or {}
            if it.get("type") == "reasoning":
                info = items.get(it.get("id"))
                if info and info["text"]:
                    out_blocks.append(summary_blocks(it["id"], info["output_index"], info["text"]))
                    injected += 1
    if injected:
        _log("[ua-proxy] injected reasoning summaries for %d item(s)" % injected)
    return "\n\n".join(out_blocks)


def _reasoning_count(data: bytes) -> tuple[int, int | None]:
    """Count reasoning events and reasoning_tokens in a streamed response body."""
    n = len(re.findall(rb'"type":\s*"reasoning', data))
    m = re.search(rb'"reasoning_tokens":\s*(\d+)', data)
    return n, m.group(1).decode() if m else None


def _log(msg: str) -> None:
    # Rotate the log by truncating once it grows past ~5MB so it can't fill the disk.
    path = os.environ.get("DS_PROXY_LOG")
    if path:
        try:
            if os.path.exists(path) and os.path.getsize(path) > 5 * 1024 * 1024:
                with open(path, "wb") as f:
                    f.truncate(0)
        except OSError:
            pass
        try:
            with open(path, "a") as f:
                f.write(msg + "\n")
        except OSError:
            pass
    else:
        # fall back to stderr
        print(msg, flush=True)


class Proxy:
    def __init__(self, port: int, upstream: str, log: str | None,
                 glance_cmd: list[str], model_map: dict[str, str]):
        self.port = port
        self.upstream = upstream.rstrip("/")
        self.log = log
        self.glance_cmd = glance_cmd
        self.model_map = model_map
        os.environ["DS_PROXY_LOG"] = log or ""

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        try:
            # ---- parse the inbound HTTP request head ----
            head = await self._read_head(reader)
            if head is None:
                await self._shutdown_quietly(writer)
                return
            req_line, headers_raw, body_head = head
            method, path, _ = req_line.split(" ", 2)
            content_length = int(_header_value(headers_raw, "content-length") or 0)

            # read the rest of the body if any
            body = bytearray(body_head)
            while len(body) < content_length:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                body.extend(chunk)
            body = bytes(body)

            # ---- rewrite headers: strip codex identity signals ----
            headers = [
                (k, v)
                for k, v in headers_raw
                if k.lower() not in STRIP_HEADER_EXACT
                and not k.lower().startswith("x-codex-")
            ]
            headers.append(("User-Agent", "python-requests/2.31.0"))
            headers.append(("Connection", "close"))

            # ---- rewrite body model: UI slug -> upstream model name ----
            orig_model = None
            try:
                parsed = json.loads(body or b"{}")
                if isinstance(parsed, dict):
                    orig_model = parsed.get("model")
                    mapped = self.model_map.get(orig_model)
                    if mapped:
                        parsed["model"] = mapped
                    try:
                        await _rewrite_image_inputs(parsed, self.glance_cmd)
                    except Exception as e:
                        _log("[ua-proxy] image rewrite failed: %r" % e)
                    body = json.dumps(parsed).encode()
            except Exception:
                pass

            self._log_request(path, method, body, orig_model)

            # ---- relay to upstream over HTTPS ----
            status, resp_headers, resp_body = await self._relay(
                method, path, body, headers
            )
            if resp_body is not None:
                try:
                    resp_body = _inject_reasoning_summaries(
                        resp_body.decode("utf-8", errors="replace")
                    ).encode("utf-8")
                except Exception as e:
                    _log("[ua-proxy] summary injection failed: %r" % e)

            # ---- send response back to client ----
            reason = _reasoning_count(resp_body) if resp_body is not None else (0, None)
            self._log_response(reason, "?" if resp_body is None else len(resp_body))
            resp_head = "HTTP/1.1 %d %s\r\n" % (
                status,
                _status_text(status),
            )
            out = resp_head.encode()
            for k, v in resp_headers:
                if k.lower() not in ("transfer-encoding", "content-length", "connection"):
                    out += ("%s: %s\r\n" % (k, v)).encode()
            out += ("Content-Length: %d\r\n" % len(resp_body or b"")).encode()
            out += b"Connection: close\r\n\r\n"
            out += resp_body or b""
            writer.write(out)
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            _log("[ua-proxy] handler error: %r" % e)
            try:
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            await self._shutdown_quietly(writer)

    @staticmethod
    async def _shutdown_quietly(writer):
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    async def _read_head(self, reader):
        # read line by line until blank line; also grab a bit of possible body
        data = b""
        try:
            while b"\r\n\r\n" not in data and len(data) < 128 * 1024:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                data += chunk
            idx = data.find(b"\r\n\r\n")
            if idx < 0:
                return None
            head, _, body_head = data.partition(b"\r\n\r\n")
            lines = head.decode("latin1").split("\r\n")
            req_line = lines[0]
            headers_raw = []
            for ln in lines[1:]:
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    headers_raw.append((k.strip(), v.strip()))
            return req_line, headers_raw, body_head
        except Exception:
            return None

    def _log_request(self, path, method, body, orig_model=None):
        try:
            parsed = json.loads(body or b"{}")
            with open("/tmp/ua_proxy_last_body.json", "w") as f:
                json.dump(parsed, f, ensure_ascii=False, indent=1)
            model = parsed.get("model")
            model_label = "%s -> %s" % (orig_model, model) if (orig_model and orig_model != model) else str(model)
            _log(
                "[ua-proxy] request %s %s model=%s reasoning=%s body_len=%d"
                % (
                    method,
                    path,
                    model_label,
                    json.dumps(parsed.get("reasoning")),
                    len(body or b""),
                )
            )
        except Exception as e:
            _log("[ua-proxy] body parse failed: %s (len=%s)" % (e, len(body or b"")))

    def _log_response(self, reason, length):
        n, toks = reason
        _log(
            "[ua-proxy] response: reasoning_events=%d reasoning_tokens=%s len=%s"
            % (n, toks if toks is not None else "?", length)
        )

    async def _relay(self, method, path, body, headers):
        url = self.upstream + path
        data = body or None
        req = request.Request(url, data=data, method=method)
        for k, v in headers:
            req.add_header(k, v)
        loop = asyncio.get_running_loop()
        try:
            resp = await loop.run_in_executor(None, lambda: request.urlopen(req, timeout=600))
        except Exception as e:
            _log("[ua-proxy] upstream error: %r" % e)
            raise
        try:
            resp_body = resp.read()
            resp_headers = [(k, v) for k, v in resp.headers.items()]
            return resp.status, resp_headers, resp_body
        finally:
            resp.close()

    async def serve(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", self.port)
        server = self.server
        _log("[ua-proxy] listening on 127.0.0.1:%d -> %s" % (self.port, self.upstream))
        async with server:
            await server.serve_forever()
        _log("[ua-proxy] server stopped")


def _status_text(code: int) -> str:
    return {
        200: "OK",
        400: "Bad Request",
        401: "Unauthorized",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        500: "Internal Server Error",
        502: "Bad Gateway",
        503: "Service Unavailable",
    }.get(code, "OK")


async def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19100)
    ap.add_argument("--upstream", default="https://api.deepseek.com")
    ap.add_argument("--log", default="")
    ap.add_argument("--glance-cmd", default="/usr/local/bin/glance",
                    help="Local vision CLI used to describe images (default: /usr/local/bin/glance)")
    ap.add_argument("--model-map", action="append", default=None,
                    metavar="SLUG=UPSTREAM",
                    help="Map a catalog model slug to an upstream model name. Repeatable.")
    ap.add_argument("--env-file", default=None,
                    help="Load KEY=VALUE pairs from a .env file (existing env vars win)")
    args = ap.parse_args()

    _load_env_file(args.env_file)

    proxy = Proxy(
        args.port,
        args.upstream,
        args.log,
        [args.glance_cmd],
        _parse_model_map(args.model_map),
    )
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except NotImplementedError:
            pass
    task = asyncio.ensure_future(proxy.serve())
    await stopped.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    asyncio.run(_main())
