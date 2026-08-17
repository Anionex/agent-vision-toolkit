#!/usr/bin/env python3
"""Local smoke test for the standalone DeepSeek vision proxy.

Runs a plain-HTTP echo upstream + the proxy (both localhost), sends a request
that carries Codex identity signals, and checks:
  - the downstream proxy response round-trips (HTTP 200)
  - optional Codex header compatibility is isolated behind a flag
  - model names pass through unchanged except for the gpt-5.2 display alias
  - a text-only request body passes through byte-for-byte
  - the response body streams through successfully
"""

import base64
import gzip
import http.client
import importlib.util
import json
import os
import subprocess
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIRST = b'data: {"type":"first"}\n\n'
SECOND = b'data: {"type":"second"}\n\n'


def main():
    py = sys.executable
    proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "vision_proxy.py")
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

        print("MODEL PASS: ordinary model names and text-only bodies are unchanged")

        alias = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
        alias.request(
            "POST", "/responses",
            body='{"model":"gpt-5.2","input":"hi"}',
            headers={"Content-Type": "application/json"},
        )
        alias_response = alias.getresponse()
        alias_response.read()
        alias.close()
        alias_body = json.load(open("/tmp/up_body.json"))
        assert alias_response.status == 200
        assert alias_body["model"] == "deepseek-v4-flash"
        print("MODEL COMPAT PASS: gpt-5.2 is forwarded as deepseek-v4-flash")

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

        # ---- other dialects: text-only bodies pass through byte-for-byte ----
        def roundtrip(path, dialect_body, extra_headers):
            conn2 = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
            conn2.request("POST", path, body=dialect_body,
                          headers={"Content-Type": "application/json", **extra_headers})
            resp2 = conn2.getresponse()
            resp2.read()
            conn2.close()
            return resp2.status, open("/tmp/up_body.json", "rb").read(), json.load(open("/tmp/up_headers.json"))

        anth_body = ('{"model":"user-configured-model","max_tokens":100,"system":"s",'
                     '"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}')
        status, raw, ups2 = roundtrip("/v1/messages", anth_body, {"x-api-key": "existing-anthropic-key"})
        assert status == 200 and raw == anth_body.encode(), (status, raw)
        assert next((v for k, v in ups2.items() if k.lower() == "x-api-key"), None) == "existing-anthropic-key"
        print("DIALECT PASS: anthropic text-only bodies pass through byte-for-byte")

        layered_raw = b'{"model":"m","input":"compressed text"}'
        layered_body = zlib.compress(gzip.compress(layered_raw))
        layered = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
        layered.putrequest("POST", "/responses")
        layered.putheader("Content-Type", "application/json")
        layered.putheader("Content-Encoding", "gzip")
        layered.putheader("Content-Encoding", "deflate")
        layered.putheader("Content-Length", str(len(layered_body)))
        layered.endheaders(layered_body)
        layered_response = layered.getresponse()
        layered_response.read()
        layered.close()
        layered_headers = json.load(open("/tmp/up_headers.json"))
        assert layered_response.status == 200, layered_response.status
        assert open("/tmp/up_body.json", "rb").read() == layered_raw
        assert not any(k.lower() == "content-encoding" for k in layered_headers)
        print("LAYERED ENCODING PASS: repeated headers decode in wire order")

        oversized = http.client.HTTPConnection("127.0.0.1", 19101, timeout=5)
        oversized.putrequest("POST", "/responses")
        oversized.putheader("Content-Type", "application/json")
        oversized.putheader("Content-Length", str(module.MAX_REQUEST_BODY_BYTES + 1))
        oversized.endheaders()
        oversized_response = oversized.getresponse()
        oversized_body = oversized_response.read()
        oversized.close()
        assert oversized_response.status == 413, oversized_response.status
        assert b"Request body exceeds" in oversized_body, oversized_body
        print("REQUEST LIMIT PASS: oversized wire bodies return 413 before reading")

        # ---- degraded: image bodies without vision config become a visible note ----
        env2 = {k: v for k, v in os.environ.items() if not k.startswith("VISION_")}
        pr2 = subprocess.Popen(
            [py, proxy_script, "--port", "19102", "--upstream", "http://127.0.0.1:19999",
             "--log", "/tmp/ds_proxy_test2.log", "--skip-vision-config-check"],
            stdout=open("/tmp/ds_proxy_proc2.log", "w"), stderr=subprocess.STDOUT, env=env2,
        )
        time.sleep(1.2)
        try:
            open("/tmp/up_body.json", "wb").close()
            for path, image_body in (
                ("/v1/messages",
                 '{"model":"m","messages":[{"role":"user","content":[{"type":"image",'
                 '"source":{"type":"base64","media_type":"image/png","data":"AAAA"}}]}]}'),
                ("/responses",
                 '{"model":"m","input":[{"type":"message","role":"user",'
                 '"content":[{"type":"input_image","image_url":"data:image/png;base64,AAAA"}]}]}'),
            ):
                conn3 = http.client.HTTPConnection("127.0.0.1", 19102, timeout=5)
                conn3.request("POST", path, body=image_body, headers={"Content-Type": "application/json"})
                resp3 = conn3.getresponse()
                resp3.read()
                conn3.close()
                assert resp3.status == 200, (path, resp3.status)

            # Codex Desktop compresses larger Responses requests with zstd.
            # This shape is the image returned by view_image, not a pasted image.
            zstd_body = base64.b64decode(
                "KLUv/SCRbQMAQgYVGYCpGgN4agW4pCOzJ1shzES6VBL05YCjqI/RiEa8lFKIYJASaiAc7QFSV9H5QkCTDmXKTA6cc6QmC51ZS49pTu1p8HCenmJfFPKFr6nJ7Hwl5NiLCAA0JVcBtIhiwoWtDNiZKGZjGKuCAg=="
            )
            conn_zstd = http.client.HTTPConnection("127.0.0.1", 19102, timeout=5)
            conn_zstd.request(
                "POST", "/responses", body=zstd_body,
                headers={"Content-Type": "application/json", "Content-Encoding": "zstd"},
            )
            zstd_response = conn_zstd.getresponse()
            zstd_response.read()
            conn_zstd.close()
            assert zstd_response.status == 200, zstd_response.status
            zstd_upstream = json.load(open("/tmp/up_body.json"))
            zstd_headers = json.load(open("/tmp/up_headers.json"))
            assert "input_image" not in json.dumps(zstd_upstream), zstd_upstream
            assert not any(k.lower() == "content-encoding" for k in zstd_headers), zstd_headers
            print("ZSTD PASS: compressed function_call_output image is decoded, rewritten, and forwarded")

            unsupported = http.client.HTTPConnection("127.0.0.1", 19102, timeout=5)
            unsupported.request(
                "POST", "/responses", body=b"{}",
                headers={"Content-Type": "application/json", "Content-Encoding": "br"},
            )
            unsupported_response = unsupported.getresponse()
            unsupported_body = unsupported_response.read()
            unsupported.close()
            assert unsupported_response.status == 415, unsupported_response.status
            assert b"Unsupported Content-Encoding: br" in unsupported_body, unsupported_body

            invalid = http.client.HTTPConnection("127.0.0.1", 19102, timeout=5)
            invalid.request(
                "POST", "/responses", body=b"not a zstd frame",
                headers={"Content-Type": "application/json", "Content-Encoding": "zstd"},
            )
            invalid_response = invalid.getresponse()
            invalid_body = invalid_response.read()
            invalid.close()
            assert invalid_response.status == 400, invalid_response.status
            assert b"Invalid zstd request body" in invalid_body, invalid_body
            print("ENCODING ERROR PASS: unsupported and invalid bodies return explicit 4xx errors")
            upb3 = json.load(open("/tmp/up_body.json"))
            assert "[vision unavailable:" in json.dumps(upb3, ensure_ascii=False), upb3
            log3 = open("/tmp/ds_proxy_test2.log").read()
            assert "image description failed" in log3 and "image rewrite degraded" in log3, log3
            print("DEGRADED PASS: no vision config -> visible note forwarded, failure logged, never 502")
        finally:
            pr2.terminate()

        # ---- broken vision API (401): request continues with a visible note ----
        vision_src = r'''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class V(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        if n:
            self.rfile.read(n)
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"error": {"message": "invalid api key"}}).encode())
    def log_message(self, *a): pass
HTTPServer(('127.0.0.1', 19998), V).serve_forever()
'''
        vision_file = "/tmp/ds_vision_401_server.py"
        with open(vision_file, "w") as f:
            f.write(vision_src)
        vision_up = subprocess.Popen([py, vision_file],
                                     stdout=open("/tmp/ds_vision_401.log", "w"), stderr=subprocess.STDOUT)
        time.sleep(0.8)
        env3 = {k: v for k, v in os.environ.items() if not k.startswith("VISION_")}
        env3.update({"VISION_BASE_URL": "http://127.0.0.1:19998",
                     "VISION_API_KEY": "bad-key", "VISION_MODEL": "vision-test"})
        pr3 = subprocess.Popen(
            [py, proxy_script, "--port", "19103", "--upstream", "http://127.0.0.1:19999",
             "--log", "/tmp/ds_proxy_test3.log", "--skip-vision-config-check"],
            stdout=open("/tmp/ds_proxy_proc3.log", "w"), stderr=subprocess.STDOUT, env=env3,
        )
        time.sleep(1.2)
        try:
            open("/tmp/up_body.json", "wb").close()
            img_resp = ('{"model":"m","input":[{"type":"message","role":"user",'
                        '"content":[{"type":"input_image","image_url":"data:image/png;base64,AAAA"}]}]}')
            conn4 = http.client.HTTPConnection("127.0.0.1", 19103, timeout=5)
            conn4.request("POST", "/responses", body=img_resp, headers={"Content-Type": "application/json"})
            resp4 = conn4.getresponse()
            resp4.read()
            conn4.close()
            up_resp = json.load(open("/tmp/up_body.json"))
            resp_content = up_resp["input"][0]["content"]
            assert resp4.status == 200, resp4.status
            assert any("[vision unavailable:" in block.get("text", "") for block in resp_content), resp_content

            open("/tmp/up_body.json", "wb").close()
            anth_img = ('{"model":"m","messages":[{"role":"user","content":[{"type":"image",'
                        '"source":{"type":"base64","media_type":"image/png","data":"AAAA"}}]}]}')
            conn5 = http.client.HTTPConnection("127.0.0.1", 19103, timeout=5)
            conn5.request("POST", "/v1/messages", body=anth_img, headers={"Content-Type": "application/json"})
            resp5 = conn5.getresponse()
            resp5.read()
            conn5.close()
            up_anth = json.load(open("/tmp/up_body.json"))
            anth_content = up_anth["messages"][0]["content"]
            assert resp5.status == 200, resp5.status
            assert any("[vision unavailable:" in block.get("text", "") for block in anth_content), anth_content

            open("/tmp/up_body.json", "wb").close()
            text_only = '{"model":"m","input":"hi"}'
            conn6 = http.client.HTTPConnection("127.0.0.1", 19103, timeout=5)
            conn6.request("POST", "/responses", body=text_only, headers={"Content-Type": "application/json"})
            resp6 = conn6.getresponse()
            resp6.read()
            conn6.close()
            assert resp6.status == 200, resp6.status
            assert open("/tmp/up_body.json", "rb").read() == text_only.encode(), "text-only body must pass through"
            log3b = open("/tmp/ds_proxy_test3.log").read()
            assert "Vision API HTTP 401" in log3b, "the 401 failure must be logged, never silent"
            print("DEGRADED PASS: vision 401 -> note in both dialects, 401 logged; text-only stays 200")
        finally:
            pr3.terminate()
            vision_up.terminate()
    finally:
        conn.close()
        up.terminate()
        pr.terminate()


if __name__ == "__main__":
    main()
