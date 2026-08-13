#!/usr/bin/env python3
"""Local smoke test for explicit upstream egress + failover.

Runs a plain-HTTP upstream, a fake CONNECT proxy, and several proxy instances
to verify the decisions that replaced implicit system-proxy following:
  - default egress is direct (no proxy configured, no system proxy consulted)
  - when every route fails, the client gets a 502 listing per-route reasons
  - on connection failure the proxy fails over to the explicit proxy
  - a working route becomes sticky for subsequent requests
  - --proxy-first tries the explicit proxy before direct

All services are localhost; the real Clash/system proxy is never touched.
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY_SCRIPT = os.path.join(REPO, "vision_proxy.py")
TMP = tempfile.mkdtemp(prefix="dsvision-egress-")

UPSTREAM_PORT = 19997
FAKE_PROXY_PORT = 19996
REFUSED_UPSTREAM = "http://127.0.0.1:1"  # direct connect is refused instantly
PROXY_URL = f"http://127.0.0.1:{FAKE_PROXY_PORT}"

UPSTREAM_SRC = f'''
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def _reply(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n:
            self.rfile.read(n)
        body = json.dumps({{"id": "egress-test", "object": "response",
                            "status": "completed", "output": []}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_POST = _reply
    do_GET = _reply
    def log_message(self, *a):
        pass
HTTPServer(("127.0.0.1", {UPSTREAM_PORT}), H).serve_forever()
'''

FAKE_PROXY_SRC = f'''
import socket
import threading

def relay(src, dst):
    try:
        while True:
            chunk = src.recv(65536)
            if not chunk:
                break
            dst.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass

def handle(conn):
    try:
        data = b""
        while b"\\r\\n\\r\\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                return
            data += chunk
        up = socket.create_connection(("127.0.0.1", {UPSTREAM_PORT}), timeout=5)
        conn.sendall(b"HTTP/1.1 200 Connection established\\r\\n\\r\\n")
        t1 = threading.Thread(target=relay, args=(conn, up), daemon=True)
        t2 = threading.Thread(target=relay, args=(up, conn), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("127.0.0.1", {FAKE_PROXY_PORT}))
server.listen(16)
while True:
    conn, _ = server.accept()
    threading.Thread(target=handle, args=(conn,), daemon=True).start()
'''


def write_script(name, source):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
    return path


def start_background(args, log_name):
    """Start a proxy whose --log is <TMP>/<log_name>. Returns (process, proxy_log)."""
    proxy_log = os.path.join(TMP, log_name)
    full_args = [*args, "--log", proxy_log]
    handle = open(proxy_log + ".stdout", "w")
    proc = subprocess.Popen(
        [sys.executable, *full_args],
        stdout=handle, stderr=subprocess.STDOUT, cwd=REPO,
    )
    return proc, proxy_log


def wait_listen(port, proc, timeout=6.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early with {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError(f"port {port} never came up")


def post(port, path="/responses"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    body = '{"model":"deepseek-chat","input":"hi"}'
    conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = resp.read().decode("utf-8", errors="replace")
    conn.close()
    return resp.status, data


def read_log(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def main():
    procs = []
    try:
        upstream_script = write_script("egress_upstream.py", UPSTREAM_SRC)
        fake_proxy_script = write_script("egress_fake_proxy.py", FAKE_PROXY_SRC)
        up = subprocess.Popen([sys.executable, upstream_script], cwd=REPO)
        fp = subprocess.Popen([sys.executable, fake_proxy_script], cwd=REPO)
        procs += [up, fp]
        time.sleep(1.0)

        base_args = [PROXY_SCRIPT, "--skip-vision-config-check"]

        # 1) default egress is direct
        direct_proc, direct_log = start_background(
            [*base_args, "--port", "19110", "--upstream", f"http://127.0.0.1:{UPSTREAM_PORT}"],
            "direct.log")
        procs.append(direct_proc)
        wait_listen(19110, direct_proc)
        status, _ = post(19110)
        direct_log_text = read_log(direct_log)
        assert status == 200, status
        assert "egress route OK: direct" in direct_log_text, direct_log_text
        assert "egress route failed" not in direct_log_text, direct_log_text
        print("EGRESS DIRECT PASS: default egress is direct, no failover noise")

        # 2) all routes failed -> 502 with per-route detail
        fail_proc, fail_log = start_background(
            [*base_args, "--port", "19111", "--upstream", REFUSED_UPSTREAM],
            "fail.log")
        procs.append(fail_proc)
        wait_listen(19111, fail_proc)
        status, data = post(19111)
        assert status == 502, (status, data)
        assert "All egress routes failed: direct ->" in data, data
        print("EGRESS ALL-FAIL PASS: 502 carries per-route failure detail")

        # 3) failover direct -> explicit proxy, then sticky
        fo_proc, fo_log = start_background(
            [*base_args, "--port", "19112", "--upstream", REFUSED_UPSTREAM,
             "--upstream-proxy", PROXY_URL],
            "fo.log")
        procs.append(fo_proc)
        wait_listen(19112, fo_proc)
        status, _ = post(19112)
        assert status == 200, status
        status, _ = post(19112)
        assert status == 200, status
        fo_log_text = read_log(fo_log)
        assert fo_log_text.count("egress route failed: direct") == 1, fo_log_text
        assert fo_log_text.count("egress route OK: proxy http://127.0.0.1:19996") == 2, fo_log_text
        print("EGRESS FAILOVER+STICKY PASS: failed once, then sticky proxy")

        # 4) --proxy-first tries the explicit proxy before direct
        pf_proc, pf_log = start_background(
            [*base_args, "--port", "19113", "--upstream", REFUSED_UPSTREAM,
             "--upstream-proxy", PROXY_URL, "--proxy-first"],
            "pf.log")
        procs.append(pf_proc)
        wait_listen(19113, pf_proc)
        status, _ = post(19113)
        assert status == 200, status
        pf_log_text = read_log(pf_log)
        assert "egress route failed" not in pf_log_text, pf_log_text
        assert "egress route OK: proxy http://127.0.0.1:19996" in pf_log_text, pf_log_text
        assert "(egress: proxy http://127.0.0.1:19996 -> direct)" in pf_log_text, pf_log_text
        print("EGRESS PROXY-FIRST PASS: proxy attempted first, direct untouched")

        print("EGRESS SMOKE PASS")
    finally:
        for proc in procs:
            try:
                proc.terminate()
            except OSError:
                pass


if __name__ == "__main__":
    main()
