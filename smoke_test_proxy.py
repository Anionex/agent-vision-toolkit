#!/usr/bin/env python3
"""Local smoke test for the standalone DeepSeek vision proxy.

Runs a plain-HTTP echo upstream + the proxy (both localhost), sends a request
that carries Codex identity signals, and checks:
  - the downstream proxy response round-trips (HTTP 200)
  - optional Codex header compatibility is isolated behind a flag
  - the user's model name and Authorization header pass through unchanged
  - a text-only request body passes through byte-for-byte
  - the response body streams through successfully
"""

import http.client
import importlib.util
import json
import os
import subprocess
import sys
import time

FIRST = b'data: {"type":"first"}\n\n'
SECOND = b'data: {"type":"second"}\n\n'


def main():
    py = sys.executable
    proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "deepseek-vision-proxy.py")
    log = "/tmp/ds_proxy_test.log"
    for path in (log, "/tmp/up_headers.json", "/tmp/up_body.json"):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    # ---- echo upstream ----
    up_src = r'''
import json, time
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(n) if n else b''
        with open('/tmp/up_headers.json', 'w') as f:
            json.dump(dict(self.headers), f)
        with open('/tmp/up_body.json', 'wb') as f:
            f.write(body)
        if self.path == '/broken':
            out = b'data: {"type":"partial"}\n\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(out) + 100))
            self.end_headers()
            self.wfile.write(out)
            self.wfile.flush()
            self.close_connection = True
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        self.wfile.write(b'data: {"type":"first"}\n\n')
        self.wfile.flush()
        time.sleep(0.6)
        self.wfile.write(b'data: {"type":"second"}\n\n')
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', 19999), H).serve_forever()
'''
    up_file = "/tmp/ds_proxy_echo_upstream.py"
    with open(up_file, "w") as f:
        f.write(up_src)

    up = subprocess.Popen([py, up_file], stdout=open("/tmp/ds_up.log", "w"), stderr=subprocess.STDOUT)
    pr = subprocess.Popen(
        [py, proxy_script, "--port", "19101", "--upstream", "http://127.0.0.1:19999",
         "--log", log,
         "--codex-header-compat", "--skip-vision-config-check"],
        stdout=open("/tmp/ds_proxy_proc.log", "w"), stderr=subprocess.STDOUT,
        env={**os.environ, "DEEPSEEK_API_KEY": "must-not-be-injected"},
    )
    time.sleep(1.2)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
        body = '{"model":"user-configured-model", "reasoning":{"effort":"none"}, "input":"hi"}'
        conn.request(
            "POST", "/responses", body=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer existing-codex-key",
                "User-Agent": "codex/0.146.0",
                "x-codex-turn-metadata": "{}",
                "originator": "Codex Desktop",
            },
        )
        resp = conn.getresponse()
        started = time.monotonic()
        first = resp.read(len(FIRST))
        first_elapsed = time.monotonic() - started
        resp_body = first + resp.read()
        print("client_http_status:", resp.status)
        print("proxy_tail:"); 
        try:
            print("  " + open(log).read().replace("\n", "\n  "))
        except FileNotFoundError:
            print("  (no log)")

        ups = json.load(open("/tmp/up_headers.json"))
        raw_upstream_body = open("/tmp/up_body.json", "rb").read()
        upb = json.loads(raw_upstream_body)
        ua = ups.get("User-Agent")
        has_xcodex = any(k.lower().startswith("x-codex-") for k in ups)
        has_originator = any(k.lower() == "originator" for k in ups)
        print("upstream User-Agent:", ua)
        print("upstream still has x-codex-* header:", has_xcodex)
        print("upstream still has originator header:", has_originator)
        print("upstream body reasoning:", upb.get("reasoning"))
        print("first streamed chunk seconds:", round(first_elapsed, 3))
        print("---------------------------------------------")
        ok = (resp.status == 200
              and ua == "python-urllib/3"
              and not has_xcodex
              and not has_originator
              and ups.get("Authorization") == "Bearer existing-codex-key"
              and upb.get("reasoning") == {"effort": "none"}
              and upb.get("model") == "user-configured-model"
              and raw_upstream_body == body.encode()
              and resp_body == FIRST + SECOND
              and first_elapsed < 0.45)
        print("SMOKE", "PASS" if ok else "FAIL")
        if not ok:
            raise SystemExit(1)

        spec = importlib.util.spec_from_file_location("vision_proxy", proxy_script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        incoming = [("Authorization", "Bearer existing-codex-key"), ("User-Agent", "codex/test"),
                    ("x-codex-test", "1"), ("originator", "Codex")]
        saved_key = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "must-not-be-injected"
        try:
            default_headers = module.Proxy(1, "http://example", "", False, False)._upstream_headers(incoming)
        finally:
            if saved_key is None:
                os.environ.pop("DEEPSEEK_API_KEY", None)
            else:
                os.environ["DEEPSEEK_API_KEY"] = saved_key
        assert ("Authorization", "Bearer existing-codex-key") in default_headers
        assert all("must-not-be-injected" not in value for _, value in default_headers)
        assert ("User-Agent", "codex/test") in default_headers
        assert ("x-codex-test", "1") in default_headers
        assert ("originator", "Codex") in default_headers
        print("DEFAULT HEADER PASS: Codex auth and identity headers are preserved unless opted in")

        print("MODEL PASS: the user's configured model name and text-only body are unchanged")

        reasoning_sse = "\r\n\r\n".join([
            'data: {"type":"response.output_item.added","item":{"type":"reasoning","id":"r1"}}',
            'data: {"type":"response.reasoning_text.delta","item_id":"r1","delta":"thought"}',
            'data: {"type":"response.output_item.done","item":{"type":"reasoning","id":"r1","summary":[]}}',
        ])
        fixed = module._inject_reasoning_summaries(reasoning_sse)
        assert '"summary_text"' in fixed and "thought" in fixed
        print("REASONING COMPAT PASS: CRLF SSE is accepted when explicitly enabled")

        broken = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
        broken.request("POST", "/broken", body=body, headers={"Content-Type": "application/json"})
        broken_response = broken.getresponse()
        broken_body = broken_response.read()
        broken.close()
        assert broken_response.status == 200
        assert b"HTTP/1.1 502" not in broken_body
        print("PARTIAL STREAM PASS: an upstream disconnect does not append a second HTTP response")
    finally:
        conn.close()
        up.terminate()
        pr.terminate()


if __name__ == "__main__":
    main()
