#!/usr/bin/env python3
"""Core retry/error test for the shared vision client and glance CLI."""

from http.server import BaseHTTPRequestHandler, HTTPServer
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
    calls = 0
    last_body = b""
    last_headers = {}

    def do_POST(self):
        Handler.calls += 1
        Handler.last_headers = dict(self.headers)
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
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    with tempfile.TemporaryDirectory() as raw:
        windows_env = Path(raw) / "agent-vision-toolkit" / "env"
        windows_env.parent.mkdir()
        windows_env.write_text("WINDOWS_ENV_PROBE=loaded\n")
        previous_local_appdata = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = raw
        os.environ.pop("WINDOWS_ENV_PROBE", None)
        try:
            vision_client.load_default_env()
            assert os.environ.get("WINDOWS_ENV_PROBE") == "loaded"
        finally:
            os.environ.pop("WINDOWS_ENV_PROBE", None)
            if previous_local_appdata is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = previous_local_appdata

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    environment = dict(os.environ, VISION_API_KEY="test-key",
                       VISION_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                       VISION_MODEL="fixture-model")
    environment.pop("VISION_USER_AGENT", None)
    saved = dict(os.environ)
    os.environ.update(environment)
    try:
        Handler.calls, Handler.statuses, Handler.bodies = 0, [429, 200], []
        assert vision_client.describe_image("data:image/png;base64,AAAA") == "fixture answer"
        assert Handler.calls == 2
        assert Handler.last_headers.get("User-Agent") == vision_client.DEFAULT_USER_AGENT
        assert not Handler.last_headers["User-Agent"].startswith("Python-urllib/")

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
        text = json.loads(Handler.last_body)["messages"][0]["content"][0]["text"]
        assert text.startswith("Please respond in English.")
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        os.environ["LANG"] = "zh"
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        finally:
            os.environ.pop("LANG", None)
        text = json.loads(Handler.last_body)["messages"][0]["content"][0]["text"]
        assert text.startswith("请使用简体中文回答。")
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        os.environ.pop("LANG", None)
        vision_client.describe_image("data:image/png;base64,AAAA")
        text = json.loads(Handler.last_body)["messages"][0]["content"][0]["text"]
        assert "Please respond in English." not in text
        assert "请使用简体中文回答。" not in text
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        vision_client.describe_image(["data:image/png;base64,AAAA", "data:image/png;base64,BBBB"])
        content = json.loads(Handler.last_body)["messages"][0]["content"]
        image_parts = [part for part in content if part.get("type") == "image_url"]
        assert len(image_parts) == 2, "a list of URLs must become one request with all images"
        assert Handler.calls == 1

        Handler.calls, Handler.statuses, Handler.bodies = 0, [200], []
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            # glance loads <repo>/.env and <cwd>/.env last, and they override the
            # process environment — run from a temp cwd whose .env carries the
            # fixture config so a developer's real .env cannot leak in.
            (Path(raw) / ".env").write_text(
                "VISION_API_KEY=test-key\n"
                f"VISION_BASE_URL=http://127.0.0.1:{server.server_port}/v1\n"
                "VISION_MODEL=fixture-model\n"
            )
            isolated_env = dict(environment, HOME=raw)
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
