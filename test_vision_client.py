#!/usr/bin/env python3
"""Core retry/error test for the shared vision client and glance CLI."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

import vision_client


class Handler(BaseHTTPRequestHandler):
    statuses = []
    calls = 0

    def do_POST(self):
        Handler.calls += 1
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        status = Handler.statuses.pop(0)
        if status == 200:
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
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    environment = dict(os.environ, VISION_API_KEY="test-key",
                       VISION_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                       VISION_MODEL="fixture-model")
    saved = dict(os.environ)
    os.environ.update(environment)
    try:
        Handler.calls, Handler.statuses = 0, [429, 200]
        assert vision_client.describe_image("data:image/png;base64,AAAA") == "fixture answer"
        assert Handler.calls == 2

        Handler.calls, Handler.statuses = 0, [401]
        try:
            vision_client.describe_image("data:image/png;base64,AAAA")
        except vision_client.VisionError:
            pass
        else:
            raise AssertionError("401 must fail cleanly")
        assert Handler.calls == 1, "401 must not be retried"

        Handler.calls, Handler.statuses = 0, [200]
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "fixture.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            result = subprocess.run(
                [str(Path(__file__).parent / "bin/glance"), str(image), "-q", "图里有什么？"],
                env=environment, text=True, capture_output=True, check=True,
            )
            assert result.stdout.strip() == "fixture answer"
    finally:
        server.shutdown()
        os.environ.clear()
        os.environ.update(saved)
    print("VISION CLIENT TEST PASS")


if __name__ == "__main__":
    main()
