#!/usr/bin/env python3
"""Core retry/error test for the shared vision client and glance CLI."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vision_client


class Handler(BaseHTTPRequestHandler):
    statuses = []
    bodies = []
    response_headers = []
    calls = 0
    last_body = b""
    last_headers = {}
    last_path = ""

    def do_POST(self):
        Handler.calls += 1
        Handler.last_headers = dict(self.headers)
        Handler.last_path = self.path
        length = int(self.headers.get("Content-Length", 0))
        Handler.last_body = self.rfile.read(length)
        status = Handler.statuses.pop(0)
        if Handler.bodies:
            body = Handler.bodies.pop(0)
        elif status == 200:
            body = json.dumps({"choices": [{"message": {"content": "fixture answer"}}]}).encode()
        else:
            body = b'{"error":{"message":"fixture error"}}'
        self.send_response(status)
        if Handler.response_headers:
            for name, value in Handler.response_headers.pop(0).items():
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        explicit_env = root / "explicit.env"
        explicit_env.write_text("ENV_PRIORITY_PROBE=explicit\n")
        windows_env = root / "local-app-data" / "agent-vision-toolkit" / "env"
        windows_env.parent.mkdir(parents=True)
        windows_env.write_text("ENV_PRIORITY_PROBE=local-app-data\n")
        cwd = root / "cwd"
        cwd.mkdir()
        (cwd / ".env").write_text("ENV_PRIORITY_PROBE=cwd\n")
        previous_cwd = Path.cwd()
        previous_home = os.environ.get("HOME")
        previous_local_appdata = os.environ.get("LOCALAPPDATA")
        previous_explicit = os.environ.get("VISION_ENV_FILE")
        previous_probe = os.environ.get("ENV_PRIORITY_PROBE")
        os.environ["HOME"] = raw
        os.environ["LOCALAPPDATA"] = str(root / "local-app-data")
        os.environ["VISION_ENV_FILE"] = str(explicit_env)
        os.environ.pop("ENV_PRIORITY_PROBE", None)
        os.chdir(cwd)
        try:
            vision_client.load_default_env()
            assert os.environ.get("ENV_PRIORITY_PROBE") == "explicit"
        finally:
            os.chdir(previous_cwd)
            for name, value in (
                ("HOME", previous_home),
                ("LOCALAPPDATA", previous_local_appdata),
                ("VISION_ENV_FILE", previous_explicit),
                ("ENV_PRIORITY_PROBE", previous_probe),
            ):
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    with tempfile.TemporaryDirectory() as raw:
        windows_env = Path(raw) / "agent-vision-toolkit" / "env"
        windows_env.parent.mkdir()
        windows_env.write_text("WINDOWS_ENV_PROBE=loaded\n")
        previous_local_appdata = os.environ.get("LOCALAPPDATA")
        previous_explicit = os.environ.get("VISION_ENV_FILE")
        os.environ["LOCALAPPDATA"] = raw
        os.environ.pop("VISION_ENV_FILE", None)
        os.environ.pop("WINDOWS_ENV_PROBE", None)
        try:
            vision_client.load_default_env()
            assert os.environ.get("WINDOWS_ENV_PROBE") == "loaded"
        finally:
            os.environ.pop("WINDOWS_ENV_PROBE", None)
            if previous_explicit is None:
                os.environ.pop("VISION_ENV_FILE", None)
            else:
                os.environ["VISION_ENV_FILE"] = previous_explicit
            if previous_local_appdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous_local_appdata

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    environment = dict(os.environ, VISION_API_KEY="test-key",
                       VISION_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                       VISION_MODEL="fixture-model")
    environment.pop("VISION_API_PROTOCOL", None)
    environment.pop("VISION_REASONING_EFFORT", None)
    environment.pop("VISION_ANTHROPIC_THINKING", None)
    environment.pop("VISION_USER_AGENT", None)
    environment.pop("VISION_ENV_FILE", None)
    saved = dict(os.environ)
    os.environ.pop("VISION_API_PROTOCOL", None)
    os.environ.pop("VISION_REASONING_EFFORT", None)
    os.environ.pop("VISION_ANTHROPIC_THINKING", None)
    os.environ.pop("VISION_USER_AGENT", None)
    os.environ.pop("VISION_ENV_FILE", None)
    os.environ.update(environment)
    try:
        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0, [429, 200], [], [{"Retry-After": "17"}, {}]
        )
        original_sleep = vision_client.time.sleep
        delays = []
        vision_client.time.sleep = delays.append
        try:
            assert vision_client.describe_image("data:image/png;base64,AAAA") == "fixture answer"
        finally:
            vision_client.time.sleep = original_sleep
        assert Handler.calls == 2
        assert delays == [17.0]
        assert Handler.last_headers.get("User-Agent") == vision_client.DEFAULT_USER_AGENT
        assert not Handler.last_headers["User-Agent"].startswith("Python-urllib/")

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0,
            [429],
            [b'{"error":{"code":"daily_rate_limit_exceeded","message":"Daily limit reached"}}'],
            [{"Retry-After": "3600"}],
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError as exc:
            assert "daily_rate_limit_exceeded" in str(exc)
        else:
            raise AssertionError("daily quota exhaustion must fail immediately")
        finally:
            vision_client.time.sleep = original_sleep
        assert Handler.calls == 1, "daily quota exhaustion must not be retried"
        assert delays == []

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0,
            [429],
            [b'{"error":{"code":"global_daily_limit_exceeded","message":"Capacity reached"}}'],
            [{"Retry-After": "3600"}],
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError as exc:
            assert "global_daily_limit_exceeded" in str(exc)
        else:
            raise AssertionError("global daily quota exhaustion must fail immediately")
        finally:
            vision_client.time.sleep = original_sleep
        assert Handler.calls == 1
        assert delays == []

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0,
            [429, 200],
            [b'{"error":{"code":"rate_limit_exceeded","message":"Retry shortly"}}'],
            [{"Retry-After": "2"}, {}],
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        try:
            assert vision_client.describe_image("data:image/png;base64,AAAA") == "fixture answer"
        finally:
            vision_client.time.sleep = original_sleep
        assert Handler.calls == 2, "transient rate limits should remain retryable"
        assert delays == [2.0]

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        os.environ["VISION_USER_AGENT"] = "custom-vision-client/2.0"
        try:
            assert vision_client.describe_image("data:image/png;base64,AAAA") == "fixture answer"
        finally:
            os.environ.pop("VISION_USER_AGENT", None)
        assert Handler.last_headers.get("User-Agent") == "custom-vision-client/2.0"
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [401], []
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError:
            pass
        else:
            raise AssertionError("401 must fail cleanly")
        assert Handler.calls == 1, "401 must not be retried"

        Handler.calls, Handler.statuses, Handler.bodies = (
            0, [403], [b'{"error":"Cloudflare 1010 rejected test-key"}']
        )
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError as exc:
            assert "test-key" not in str(exc)
            assert "<redacted>" in str(exc)
        else:
            raise AssertionError("HTTP errors must fail cleanly")
        assert Handler.calls == 1, "403 must not be retried"

        original_urlopen = vision_client.urllib.request.urlopen
        original_sleep = vision_client.time.sleep

        def fail_with_secret(*_args, **_kwargs):
            raise urllib.error.URLError("connection failed for test-key")

        vision_client.urllib.request.urlopen = fail_with_secret
        vision_client.time.sleep = lambda _seconds: None
        try:
            try:
                vision_client.describe_image("data:image/png;base64,AAAA")
            except vision_client.VisionError as exc:
                assert "test-key" not in str(exc)
                assert "<redacted>" in str(exc)
            else:
                raise AssertionError("network errors must fail with redacted details")
        finally:
            vision_client.urllib.request.urlopen = original_urlopen
            vision_client.time.sleep = original_sleep

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        os.environ["LANG"] = "en"
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        finally:
            os.environ.pop("LANG", None)
        parts = json.loads(Handler.last_body)["messages"][0]["content"]
        text = next(part["text"] for part in parts if part.get("type") == "text")
        assert text.startswith("Please respond in English.")
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        os.environ["LANG"] = "zh"
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        finally:
            os.environ.pop("LANG", None)
        parts = json.loads(Handler.last_body)["messages"][0]["content"]
        text = next(part["text"] for part in parts if part.get("type") == "text")
        assert text.startswith("请使用简体中文回答。")
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        os.environ.pop("LANG", None)
        vision_client.describe_image("data:image/png;base64,AAAA")
        parts = json.loads(Handler.last_body)["messages"][0]["content"]
        text = next(part["text"] for part in parts if part.get("type") == "text")
        assert "Please respond in English." not in text
        assert "请使用简体中文回答。" not in text
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        vision_client.describe_image(["data:image/png;base64,AAAA", "data:image/png;base64,BBBB"])
        content = json.loads(Handler.last_body)["messages"][0]["content"]
        assert content[0].get("type") == "image_url", \
            "vision payloads must put image parts before text for OpenCode Go MiMo compatibility"
        assert Handler.last_headers.get("User-Agent") == vision_client.DEFAULT_USER_AGENT
        image_parts = [part for part in content if part.get("type") == "image_url"]
        assert len(image_parts) == 2, "a list of URLs must become one request with all images"
        assert Handler.calls == 1

        gzip_body = gzip.compress(json.dumps({
            "choices": [{"message": {"content": "gzip fixture answer"}}],
        }).encode())
        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0, [200], [gzip_body], [{"Content-Encoding": "gzip"}]
        )
        assert vision_client.describe_image("data:image/png;base64,AAAA") == "gzip fixture answer"
        assert Handler.calls == 1, "a gzip response must be decompressed on the first try"

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0,
            [500, 500, 500],
            [gzip.compress(b'{"error":{"message":"gzip error body"}}')] * 3,
            [{"Content-Encoding": "gzip"}] * 3,
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError as exc:
            assert "gzip error body" in str(exc)
        else:
            raise AssertionError("a gzip HTTP error body must still surface the decoded message")
        finally:
            vision_client.time.sleep = original_sleep

        invalid_gzip = b"\x1f\x8btruncated"
        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0,
            [200, 200, 200],
            [invalid_gzip] * 3,
            [{"Content-Encoding": "gzip"}] * 3,
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError as exc:
            assert "Invalid gzip response body" in str(exc)
        else:
            raise AssertionError("a corrupt gzip success response must raise VisionError")
        finally:
            vision_client.time.sleep = original_sleep
        assert Handler.calls == 3, "a corrupt gzip success response must use bounded retries"
        assert delays == [1, 2]

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0,
            [500, 500, 500],
            [invalid_gzip] * 3,
            [{"Content-Encoding": "gzip"}] * 3,
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError as exc:
            assert "Vision API HTTP 500: Invalid gzip response body" in str(exc)
        else:
            raise AssertionError("a corrupt gzip HTTP error body must raise VisionError")
        finally:
            vision_client.time.sleep = original_sleep
        assert Handler.calls == 3, "a corrupt gzip HTTP error body must use bounded retries"
        assert delays == [1, 2]

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = 0, [200], [], []
        os.environ["VISION_API_PROTOCOL"] = "chat_completions"
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
        payload = json.loads(Handler.last_body)
        assert payload.get("stream") is False, \
            "chat_completions must request a non-streaming response"
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = 0, [200], [json.dumps({
            "object": "response",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "responses fixture answer"}],
            }],
        }).encode()], []
        os.environ["VISION_API_PROTOCOL"] = "responses"
        os.environ["VISION_REASONING_EFFORT"] = "medium"
        try:
            assert vision_client.describe_image(
                ["data:image/png;base64,AAAA", "data:image/png;base64,BBBB"],
                prompt="read both images",
                max_tokens=123,
            ) == "responses fixture answer"
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
            os.environ.pop("VISION_REASONING_EFFORT", None)
        assert Handler.last_path == "/v1/responses"
        payload = json.loads(Handler.last_body)
        content = payload["input"][0]["content"]
        assert [part["type"] for part in content] == ["input_image", "input_image", "input_text"]
        assert payload["store"] is False
        assert payload["max_output_tokens"] == 123
        assert payload["reasoning"] == {"effort": "medium"}
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], [json.dumps({
            "content": [
                {"type": "thinking", "thinking": "internal reasoning"},
                {"type": "text", "text": "anthropic fixture answer"},
                {"type": "text", "text": "second text block"},
            ],
            "usage": {"input_tokens": 42, "output_tokens": 7},
        }).encode()]
        os.environ["VISION_API_PROTOCOL"] = "anthropic"
        try:
            assert vision_client.describe_image(
                ["data:image/png;base64,AAAA", "https://example.com/remote.webp"],
                prompt="read both images",
                max_tokens=123,
            ) == "anthropic fixture answer\nsecond text block"
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
        assert Handler.last_path == "/v1/messages"
        assert next(v for k, v in Handler.last_headers.items() if k.lower() == "x-api-key") == "test-key"
        assert next(v for k, v in Handler.last_headers.items() if k.lower() == "anthropic-version") == "2023-06-01"
        assert not any(k.lower() == "authorization" for k in Handler.last_headers)
        payload = json.loads(Handler.last_body)
        assert payload["max_tokens"] == 123
        assert "thinking" not in payload
        content = payload["messages"][0]["content"]
        assert [part["type"] for part in content] == ["image", "image", "text"]
        assert content[0]["source"] == {
            "type": "base64", "media_type": "image/png", "data": "AAAA"
        }
        assert content[1]["source"] == {"type": "url", "url": "https://example.com/remote.webp"}
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = (
            0, [529, 200], [b'{"error":{"type":"overloaded_error"}}', json.dumps({
                "content": [{"type": "text", "text": "recovered"}],
            }).encode()], [{"Retry-After": "3"}, {}]
        )
        delays = []
        original_sleep = vision_client.time.sleep
        vision_client.time.sleep = delays.append
        os.environ["VISION_API_PROTOCOL"] = "anthropic"
        os.environ["VISION_ANTHROPIC_THINKING"] = "disabled"
        try:
            assert vision_client.describe_image("data:image/png;base64,AAAA") == "recovered"
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
            os.environ.pop("VISION_ANTHROPIC_THINKING", None)
            vision_client.time.sleep = original_sleep
        assert json.loads(Handler.last_body)["thinking"] == {"type": "disabled"}
        assert delays == [3.0]
        assert Handler.calls == 2

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], [json.dumps({
            "content": [{"type": "text", "text": "adaptive answer"}],
        }).encode()]
        os.environ["VISION_API_PROTOCOL"] = "anthropic"
        os.environ["VISION_ANTHROPIC_THINKING"] = "adaptive"
        try:
            assert vision_client.describe_image("data:image/png;base64,AAAA") == "adaptive answer"
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
            os.environ.pop("VISION_ANTHROPIC_THINKING", None)
        assert json.loads(Handler.last_body)["thinking"] == {"type": "adaptive"}
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies, Handler.response_headers = 0, [], [], []
        os.environ["VISION_API_PROTOCOL"] = "anthropic"
        os.environ["VISION_ANTHROPIC_THINKING"] = "unsupported"
        try:
            try:
                vision_client.describe_image("data:image/png;base64,AAAA")
            except vision_client.VisionError as exc:
                assert "Unsupported VISION_ANTHROPIC_THINKING" in str(exc)
            else:
                raise AssertionError("an unsupported thinking mode must fail before making a request")
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
            os.environ.pop("VISION_ANTHROPIC_THINKING", None)
        assert Handler.calls == 0

        Handler.calls, Handler.statuses, Handler.bodies = 0, [], []
        os.environ["VISION_API_PROTOCOL"] = "unsupported"
        try:
            try:
                vision_client.describe_image("data:image/png;base64,AAAA")
            except vision_client.VisionError as exc:
                assert "Unsupported VISION_API_PROTOCOL" in str(exc)
            else:
                raise AssertionError("an unsupported protocol must fail before making a request")
        finally:
            os.environ.pop("VISION_API_PROTOCOL", None)
        assert Handler.calls == 0

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            # Pin the subprocess to one explicit fixture file so caller and
            # checkout env files cannot redirect requests away from the server.
            fixture_env = Path(raw) / "vision.env"
            fixture_env.write_text(
                "VISION_API_KEY=test-key\n"
                f"VISION_BASE_URL=http://127.0.0.1:{server.server_port}/v1\n"
                "VISION_MODEL=fixture-model\n"
                "VISION_API_PROTOCOL=chat_completions\n"
            )
            isolated_env = dict(environment, HOME=raw, VISION_ENV_FILE=str(fixture_env))
            glance = Path(__file__).resolve().parent.parent / "bin/glance"
            glance_cmd = [sys.executable, str(glance)] if os.name == "nt" else [str(glance)]
            result = subprocess.run(
                [*glance_cmd, str(image), "-q", "图里有什么？"],
                env=isolated_env, cwd=raw, text=True, capture_output=True, check=True,
            )
            assert result.stdout.strip() == "fixture answer"

            Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
            result = subprocess.run(
                [*glance_cmd, str(image), str(image), "-q", "differences?"],
                env=isolated_env, cwd=raw, text=True, capture_output=True, check=True,
            )
            assert result.stdout.strip() == "fixture answer"
            content = json.loads(Handler.last_body)["messages"][0]["content"]
            assert sum(part.get("type") == "image_url" for part in content) == 2, \
                "glance with two paths must send both images in one call"
    finally:
        server.shutdown()
        os.environ.clear()
        os.environ.update(saved)
    print("VISION CLIENT TEST PASS")


if __name__ == "__main__":
    main()
