#!/usr/bin/env python3
"""Image-to-text proxy for using text-only DeepSeek models from Codex."""

from __future__ import annotations

import argparse
import asyncio
from http import HTTPStatus
import hashlib
import json
import os
import signal
import urllib.error
import urllib.request

from vision_client import VisionError, describe_image, load_env_file, validate_vision_config

HOP_HEADERS = {"connection", "content-length", "host", "proxy-connection", "te", "trailer", "transfer-encoding", "upgrade"}
CODEX_HEADERS = {"originator", "session-id", "thread-id", "user-agent"}


def _header_value(headers, name):
    return next((value for key, value in headers if key.lower() == name.lower()), None)


_DESC_CACHE = {}


def _log(message):
    path = os.environ.get("DS_VISION_PROXY_LOG", "")
    if path:
        try:
            if os.path.exists(path) and os.path.getsize(path) > 5 * 1024 * 1024:
                open(path, "w").close()
            with open(path, "a") as handle:
                handle.write(message + "\n")
            return
        except OSError:
            pass
    print(message, file=os.sys.stderr, flush=True)


def _image_desc_from_url(image_url):
    key = hashlib.sha256(image_url.encode()).hexdigest()
    cached = _DESC_CACHE.get(key)
    if cached is not None:
        return cached
    description = describe_image(image_url)
    if len(_DESC_CACHE) >= 128:
        _DESC_CACHE.pop(next(iter(_DESC_CACHE)))
    _DESC_CACHE[key] = description
    return description


async def _rewrite_image_inputs(parsed):
    inputs = parsed.get("input")
    if not isinstance(inputs, list):
        return False
    jobs = []
    for item in inputs:
        if not isinstance(item, dict):
            continue
        for field in ("content", "output"):
            values = item.get(field)
            if not isinstance(values, list):
                continue
            for index, value in enumerate(values):
                if isinstance(value, dict) and value.get("type") == "input_image" and isinstance(value.get("image_url"), str):
                    jobs.append((item, field, index, value["image_url"]))
    if not jobs:
        return False
    urls = list(dict.fromkeys(job[3] for job in jobs))
    semaphore = asyncio.Semaphore(4)

    async def run(url):
        async with semaphore:
            try:
                return url, await asyncio.to_thread(_image_desc_from_url, url)
            except VisionError as exc:
                _log(f"[vision-proxy] image description failed: {exc}")
                return url, exc

    results = await asyncio.gather(*(run(url) for url in urls))
    descriptions = {}
    errors = []
    for url, value in results:
        if value is None or isinstance(value, VisionError):
            errors.append(str(value) if isinstance(value, VisionError) else "image description failed")
        else:
            descriptions[url] = value
    if errors:
        details = "；".join(dict.fromkeys(errors))
        raise VisionError(
            f"{len(errors)} image(s) failed to describe; original images were not forwarded to the text-only model: {details}"
        )
    prefix = "[vision model description] "
    for item, field, index, url in jobs:
        item[field][index] = {"type": "input_text", "text": prefix + descriptions[url]}
    _log(f"[vision-proxy] image rewrite ok images={len(urls)} cache_entries={len(_DESC_CACHE)}")
    return True


def _rewrite_model_compat(parsed):
    if parsed.get("model") != "gpt-5.2":
        return False
    parsed["model"] = "deepseek-v4-flash"
    _log("[vision-proxy] model compatibility gpt-5.2 -> deepseek-v4-flash")
    return True


def _inject_reasoning_summaries(text):
    """Optional compatibility transform; disabled by default."""
    text = text.replace("\r\n", "\n")
    blocks = text.split("\n\n")
    parsed, items = [], {}
    for block in blocks:
        data = next((line[5:].strip() for line in block.splitlines() if line.startswith("data:")), None)
        try:
            obj = json.loads(data) if data else None
        except json.JSONDecodeError:
            obj = None
        parsed.append((obj, block))
        if not obj:
            continue
        kind = obj.get("type")
        if kind == "response.output_item.added":
            item = obj.get("item") or {}
            if item.get("type") == "reasoning" and item.get("id"):
                items[item["id"]] = ""
        elif kind == "response.reasoning_text.delta" and obj.get("item_id") in items:
            items[obj["item_id"]] += obj.get("delta", "")
        elif kind == "response.reasoning_text.done" and obj.get("item_id") in items:
            items[obj["item_id"]] = obj.get("text", items[obj["item_id"]])
    output = []
    for obj, block in parsed:
        if obj and obj.get("type") == "response.output_item.done":
            item = obj.get("item") or {}
            reasoning = items.get(item.get("id"), "")
            if item.get("type") == "reasoning" and reasoning:
                fixed = json.loads(json.dumps(obj))
                fixed["item"]["summary"] = [{"type": "summary_text", "text": reasoning}]
                block = "event: response.output_item.done\ndata: " + json.dumps(fixed, ensure_ascii=False)
        output.append(block)
    return "\n\n".join(output)


class Proxy:
    def __init__(self, port, upstream, log_path, codex_header_compat=False, inject_reasoning_summary=False):
        self.port = port
        self.upstream = upstream.rstrip("/")
        self.codex_header_compat = codex_header_compat
        self.inject_reasoning_summary = inject_reasoning_summary
        os.environ["DS_VISION_PROXY_LOG"] = log_path

    def _upstream_headers(self, incoming):
        headers = []
        for key, value in incoming:
            lower = key.lower()
            if lower in HOP_HEADERS:
                continue
            if self.codex_header_compat and (lower in CODEX_HEADERS or lower.startswith("x-codex-")):
                continue
            headers.append((key, value))
        if self.codex_header_compat:
            headers.append(("User-Agent", "python-urllib/3"))
        headers.append(("Connection", "close"))
        return headers

    async def handle(self, reader, writer):
        response = None
        response_started = False
        try:
            request_head = await self._read_head(reader)
            if request_head is None:
                return
            request_line, incoming_headers, body_start = request_head
            method, path, _ = request_line.split(" ", 2)
            try:
                content_length = int(_header_value(incoming_headers, "content-length") or 0)
            except ValueError:
                await self._send_error(writer, 400, "invalid Content-Length")
                return
            body = bytearray(body_start)
            while len(body) < content_length:
                chunk = await reader.read(min(65536, content_length - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) < content_length:
                await self._send_error(writer, 400, "incomplete request body")
                return
            parsed = None
            if body:
                try:
                    parsed = json.loads(bytes(body))
                except json.JSONDecodeError:
                    pass
            if isinstance(parsed, dict):
                image_changed = await _rewrite_image_inputs(parsed)
                model_changed = _rewrite_model_compat(parsed)
                if image_changed or model_changed:
                    body = bytearray(json.dumps(parsed).encode())
            model = parsed.get("model") if isinstance(parsed, dict) else None
            _log(f"[vision-proxy] request {method} {path} model={model} body_bytes={len(body)}")
            response = await self._open_upstream(method, path, bytes(body), self._upstream_headers(incoming_headers))
            response_started = True
            await self._send_response(writer, response)
        except VisionError as exc:
            await self._send_error(writer, 502, str(exc))
        except (ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            _log(f"[vision-proxy] handler error: {exc!r}")
            if not response_started:
                await self._send_error(writer, 502, "Upstream proxy request failed")
        finally:
            if response is not None:
                response.close()
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _open_upstream(self, method, path, body, headers):
        request = urllib.request.Request(self.upstream + path, data=body or None, method=method)
        for key, value in headers:
            request.add_header(key, value)

        def open_request():
            try:
                return urllib.request.urlopen(request, timeout=600)
            except urllib.error.HTTPError as exc:
                return exc

        try:
            return await asyncio.to_thread(open_request)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Upstream network error: {exc.reason}") from exc

    async def _send_response(self, writer, response):
        status = getattr(response, "status", None) or getattr(response, "code", 502)
        headers = list(response.headers.items())
        if self.inject_reasoning_summary and "text/event-stream" in response.headers.get("Content-Type", "") and not response.headers.get("Content-Encoding"):
            body = await asyncio.to_thread(response.read)
            body = _inject_reasoning_summaries(body.decode(errors="replace")).encode()
            await self._write_head(writer, status, headers, len(body))
            writer.write(body)
            await writer.drain()
            return

        await self._write_head(writer, status, headers, None)
        read_chunk = getattr(response, "read1", response.read)
        while chunk := await asyncio.to_thread(read_chunk, 65536):
            writer.write(chunk)
            await writer.drain()

    async def _write_head(self, writer, status, headers, content_length):
        reason = HTTPStatus(status).phrase if status in HTTPStatus._value2member_map_ else "Unknown"
        output = f"HTTP/1.1 {status} {reason}\r\n".encode()
        for key, value in headers:
            if key.lower() not in HOP_HEADERS:
                output += f"{key}: {value}\r\n".encode("latin1")
        if content_length is not None:
            output += f"Content-Length: {content_length}\r\n".encode()
        writer.write(output + b"Connection: close\r\n\r\n")
        await writer.drain()

    async def _send_error(self, writer, status, message):
        if writer.is_closing():
            return
        body = json.dumps({"error": {"message": message, "type": "proxy_error"}}, ensure_ascii=False).encode()
        writer.write(f"HTTP/1.1 {status} {HTTPStatus(status).phrase}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        await writer.drain()

    @staticmethod
    async def _read_head(reader):
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 128 * 1024:
            chunk = await reader.read(4096)
            if not chunk:
                break
            data += chunk
        if b"\r\n\r\n" not in data:
            return None
        head, _, body = data.partition(b"\r\n\r\n")
        lines = head.decode("latin1").split("\r\n")
        headers = []
        for line in lines[1:]:
            if ":" in line:
                key, _, value = line.partition(":")
                headers.append((key.strip(), value.strip()))
        return lines[0], headers, body

    async def serve(self):
        server = await asyncio.start_server(self.handle, "127.0.0.1", self.port)
        _log(f"[vision-proxy] listening on 127.0.0.1:{self.port} -> {self.upstream}")
        async with server:
            await server.serve_forever()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=19100)
    parser.add_argument("--upstream", default="https://api.deepseek.com")
    parser.add_argument("--log", default="")
    parser.add_argument("--env-file")
    parser.add_argument("--codex-header-compat", action="store_true")
    parser.add_argument("--inject-reasoning-summary", action="store_true")
    parser.add_argument("--skip-vision-config-check", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    load_env_file(args.env_file)
    if not args.skip_vision_config_check:
        try:
            validate_vision_config()
        except VisionError as exc:
            parser.error(str(exc))
    proxy = Proxy(args.port, args.upstream, args.log, args.codex_header_compat, args.inject_reasoning_summary)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stopped.set)
        except NotImplementedError:
            pass
    task = asyncio.create_task(proxy.serve())
    await stopped.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
