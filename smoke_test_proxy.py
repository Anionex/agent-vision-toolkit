#!/usr/bin/env python3
"""Local smoke test for the asyncio DeepSeek UA-rewrite proxy.

Runs a plain-HTTP echo upstream + the proxy (both localhost), sends a request
that carries Codex identity signals, and checks:
  - the downstream proxy response round-trips (HTTP 200)
  - the upstream saw a rewritten generic UA
  - the x-codex-* / originator headers were stripped
  - the request body (with reasoning.effort=none) is the same
"""

import concurrent.futures as cf
import http.client
import json
import os
import subprocess
import sys
import time


def main():
    py = sys.executable
    proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "deepseek-ua-rewrite-proxy.py")
    log = "/tmp/ds_proxy_test.log"

    # ---- echo upstream ----
    up_src = r'''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(n) if n else b''
        with open('/tmp/up_headers.json', 'w') as f:
            json.dump(dict(self.headers), f)
        with open('/tmp/up_body.json', 'wb') as f:
            f.write(body)
        out = b'data: {"type":"output_item","data":"ok"}\n\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out)
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', 19999), H).serve_forever()
'''
    up_file = "/tmp/ds_proxy_echo_upstream.py"
    with open(up_file, "w") as f:
        f.write(up_src)

    up = subprocess.Popen([py, up_file], stdout=open("/tmp/ds_up.log", "w"), stderr=subprocess.STDOUT)
    pr = subprocess.Popen(
        [py, proxy_script, "--port", "19101", "--upstream", "http://127.0.0.1:19999", "--log", log],
        stdout=open("/tmp/ds_proxy_proc.log", "w"), stderr=subprocess.STDOUT,
    )
    time.sleep(1.2)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
        body = json.dumps({"model": "deepseek-v4-flash", "reasoning": {"effort": "none"}, "input": "hi"})
        conn.request(
            "POST", "/responses", body=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "codex/0.146.0",
                "x-codex-turn-metadata": "{}",
                "originator": "Codex Desktop",
            },
        )
        resp = conn.getresponse()
        resp_body = resp.read().decode()
        print("client_http_status:", resp.status)
        print("proxy_tail:"); 
        try:
            print("  " + open(log).read().replace("\n", "\n  "))
        except FileNotFoundError:
            print("  (no log)")

        ups = json.load(open("/tmp/up_headers.json"))
        upb = json.load(open("/tmp/up_body.json"))
        ua = ups.get("User-Agent")
        has_xcodex = any(k.lower().startswith("x-codex-") for k in ups)
        has_originator = any(k.lower() == "originator" for k in ups)
        print("upstream User-Agent:", ua)
        print("upstream still has x-codex-* header:", has_xcodex)
        print("upstream still has originator header:", has_originator)
        print("upstream body reasoning:", upb.get("reasoning"))
        print("---------------------------------------------")
        ok = (resp.status == 200
              and ua == "python-requests/2.31.0"
              and not has_xcodex
              and not has_originator
              and upb.get("reasoning") == {"effort": "none"})
        print("SMOKE", "PASS" if ok else "FAIL")
    finally:
        conn.close()
        up.terminate()
        pr.terminate()


if __name__ == "__main__":
    main()
