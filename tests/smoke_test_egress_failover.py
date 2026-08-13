#!/usr/bin/env python3
"""Local smoke test for explicit upstream egress and failure-only failover."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time

REPO = Path(__file__).resolve().parent.parent
PROXY_SCRIPT = REPO / "vision_proxy.py"
PROCESSES = []
SERVERS = []
STREAM_RELEASE = threading.Event()
STREAM_RELEASED = threading.Event()

TEST_CERT = """-----BEGIN CERTIFICATE-----
MIIDQzCCAiugAwIBAgIUPjilU3tHm6cINWqNEJStWBcHz80wDQYJKoZIhvcNAQEL
BQAwGjEYMBYGA1UEAwwPcHJveHktb25seS50ZXN0MB4XDTI2MDgxMzE4MDQxNVoX
DTM2MDgxMDE4MDQxNVowGjEYMBYGA1UEAwwPcHJveHktb25seS50ZXN0MIIBIjAN
BgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApRZ17uVz3yWaYQHGt3JXYfE02hgA
HBDMSGsa7Eiqxq5/zMSPLEIhDNIJBT2A22/y6bFtlExWuKov6oENcyA8ZdsIy9iX
23ChcaqzQmiVXEEi6hzQfhC2NCl8uhBPh63pDWNfilUoRmb0/Xw2NJm5r/OfSjvl
l/m2PZxMB3+N8FJsSNqkNc0mDQ8JZ6BN3E5o2EN+13Q1QXnodSro4jhhmXJbU4Vi
L/quCAU3pWwr2bu1wi5f/oclwHD5L2umawged99YbejA3crYueCa1fOIKw95NZpF
7BCoLy686e8PjU50RcchR9XmQQf0c7Krr96/rHx06jbfs0LpaoBvAIs4pQIDAQAB
o4GAMH4wHQYDVR0OBBYEFBC0INqI8Qcgo5St9OXB9uhdhUdxMB8GA1UdIwQYMBaA
FBC0INqI8Qcgo5St9OXB9uhdhUdxMA8GA1UdEwEB/wQFMAMBAf8wKwYDVR0RBCQw
IoIPcHJveHktb25seS50ZXN0gglsb2NhbGhvc3SHBH8AAAEwDQYJKoZIhvcNAQEL
BQADggEBAEg5Q2cE4uI2s2MVPgaXWuYxooNzB5893qZIlij3i+9ZlDtCWubwEskP
0uPhwB0iOhFgQRCC1Vr996px3qGA2SVJXlaX+eo2aBGFLkxRNj/riynfUMSGKEub
1R2bnTqRUnrRQgZZ3fc7kezafGeG0xfnVYFE1l8XhAxOnsG2cpctJnXxaI4QUCz8
IbdCSd3Ddp8ryb+uQgaqZBv6ow/ZGvKJZ9x11c2LjJJIXmzB2OVBWI25amveYOpD
IZVRgRecEjlpZqOjSZmhik9xYO1OGmdwfHssWW+QQ3EGMumujGwqmxQKi3jT1mxI
m0ASqB5tjGzIpGmBXULBR9r5Zmv0nDk=
-----END CERTIFICATE-----
"""

TEST_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQClFnXu5XPfJZph
Aca3cldh8TTaGAAcEMxIaxrsSKrGrn/MxI8sQiEM0gkFPYDbb/LpsW2UTFa4qi/q
gQ1zIDxl2wjL2JfbcKFxqrNCaJVcQSLqHNB+ELY0KXy6EE+HrekNY1+KVShGZvT9
fDY0mbmv859KO+WX+bY9nEwHf43wUmxI2qQ1zSYNDwlnoE3cTmjYQ37XdDVBeeh1
KujiOGGZcltThWIv+q4IBTelbCvZu7XCLl/+hyXAcPkva6ZrCB5331ht6MDdyti5
4JrV84grD3k1mkXsEKgvLrzp7w+NTnRFxyFH1eZBB/Rzsquv3r+sfHTqNt+zQulq
gG8AizilAgMBAAECggEAEe/BS335m26Z+d04CnltXhJXdDS0WlhG4b1lVPPGPkT6
VLSse5oJvjtZyIx4oh7lLRfeeITczT6MazWvUOlZNpXYPFGhmjGAEPoDdP0o8TeQ
hBAyZOgK69rwFsUr5ulxz0cTO9PpxtBr4NisiQWEw8W78lRUqzDx6HrBVfU5ZjlZ
p1kHGKt0zfibNfsS8Dswt0xpXuujmQr8+JGMkMEDSu0JYApwWomJ4talENqe3ns8
i4eZ31y1NiSKVBWKBcgYf9bUqPRNHTiknbWlZyEYw/WoiYGJpW91Nr40FqO3O9ib
fsmQJTpfoeDxRbtnnJbC4A3r9LR177/Mjf0oGArcIQKBgQDOWJlFnfciB/c1e2Jk
VoX6jvHXg5F0pyk3xMSlTjPXU8bUiJNSUb25lhYUy4/Trhn0l3dEddCUYjnAIREX
remgx8VAR7DqMXbxXxB7tc3AdqxcQ3DxHRl7HOmYAd8J9YQjEHgiAAIjWfesEiaZ
UYFmnpnyHVLQfJVbyy9X3SUK0QKBgQDM0EBGY9QqQg3Fxbn4JPCueuSV5ZCncoxx
W0ySMgtVXsViMLdD8jtJK+71tnDWnKB6L96D2gRUnRZvaW0fi0REWJBJzrYHjMCO
4X/s6HBr3KOFq3VGiUkpEstcbD/FeChkiVh0guWCSW1SjKFA35m/2WIo9+k7RA/R
i1Zoi65dlQKBgBDJvI6hb33hUAeV5kdrkrLz9lEmbysifoP/ClC4sBcQxdh81B+a
bukugNVoSmdaftobiKSVQUcRRsmO5ykaCSv/lNjJ/GbRZ2/z4A9wlzDVduh6xDGZ
wHz3uTmYzWCuDPYdXOjHP2VI6JGjWGiY7QJAXR4JrLcxq6UwPsXTRDRBAoGAXFuY
cGV5+ihZL5LvPp/hzLxsMdAYf/nerQtfpxlcFP4sgg+3xLMJ2wAtvK2tiomMsCy/
6bM5erJvuIPRCoVxnmRVhILrgNIOzx+O4VUbxPf04UUlGE62KAhqnd3OkAyUImnw
8nFIb40O+EekO63ZFjM/2XuZt/kELRjpOTGrylUCgYEAqo7TxWDOQikjJzY4YmDN
NqIE23FPEgdx6wl5FOz79MSW/cNFKBOE04HzjSAhpm6CpwZiqgKyviQsv3zXcyOB
WX8ELqeZrH4wBmaJWDqRLPo3+E5ivw4qw97ikBam/+VG6UsqnRpidfVm3WZteWiZ
d017fcDs5v7mtJc+11OZ/OQ=
-----END PRIVATE KEY-----
"""


def load_proxy_module():
    sys.path.insert(0, str(REPO))
    spec = importlib.util.spec_from_file_location("egress_vision_proxy", PROXY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def create_test_certificate(tmp):
    cert = tmp / "cert.pem"
    key = tmp / "key.pem"
    cert.write_text(TEST_CERT, encoding="ascii")
    key.write_text(TEST_KEY, encoding="ascii")
    return cert, key


class UpstreamHandler(BaseHTTPRequestHandler):
    records = []

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(size) if size else b""
        self.records.append({
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        })
        if self.path == "/status":
            payload = b'{"error":"expected"}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"part":1}\n\n')
            self.wfile.flush()
            if STREAM_RELEASE.wait(timeout=5):
                STREAM_RELEASED.set()
            self.wfile.write(b'data: {"part":2}\n\n')
            self.wfile.flush()
            return
        payload = json.dumps({
            "id": "egress-test", "object": "response",
            "status": "completed", "output": [],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


class ConnectProxyHandler(socketserver.BaseRequestHandler):
    authorities = []
    target_port = None

    def handle(self):
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 64 * 1024:
            chunk = self.request.recv(4096)
            if not chunk:
                return
            data += chunk
        first_line = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split(" ")
        if len(parts) != 3 or parts[0] != "CONNECT":
            self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            return
        authority = parts[1]
        self.authorities.append(authority)
        expected = f"127.0.0.1:{self.server.expected_authority_port}"
        if authority != expected:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        upstream = socket.create_connection(("127.0.0.1", self.target_port), timeout=5)
        self.request.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
        threads = [
            threading.Thread(target=self.relay, args=(self.request, upstream), daemon=True),
            threading.Thread(target=self.relay, args=(upstream, self.request), daemon=True),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        upstream.close()

    @staticmethod
    def relay(source, destination):
        try:
            while chunk := source.recv(65536):
                destination.sendall(chunk)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


class ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_tls_upstream(cert, key):
    server = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_connect_proxy(target_port, expected_authority_port):
    ConnectProxyHandler.target_port = target_port
    server = ThreadingTCPServer(("127.0.0.1", 0), ConnectProxyHandler)
    server.expected_authority_port = expected_authority_port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def start_proxy(tmp, port, upstream, cert, *extra):
    log = tmp / f"proxy-{port}.log"
    stdout = open(tmp / f"proxy-{port}.stdout", "w", encoding="utf-8")
    env = dict(os.environ)
    env.update({
        "SSL_CERT_FILE": str(cert),
        "HTTP_PROXY": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
        "NO_PROXY": "",
    })
    proc = subprocess.Popen([
        sys.executable, str(PROXY_SCRIPT), "--skip-vision-config-check",
        "--port", str(port), "--upstream", upstream, "--log", str(log),
        *extra,
    ], stdout=stdout, stderr=subprocess.STDOUT, cwd=REPO, env=env)
    proc.stdout_handle = stdout
    return proc, log


def wait_listen(port, proc, timeout=7.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"process exited early with {proc.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"port {port} never came up")


def post(port, path="/responses", body=b'{"model":"deepseek-chat","input":"hi"}', headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    conn.request("POST", path, body=body, headers=request_headers)
    response = conn.getresponse()
    data = response.read()
    status = response.status
    conn.close()
    return status, data


def read_log(path):
    return path.read_text(encoding="utf-8", errors="replace")


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    proc.stdout_handle.close()


def test_route_validation_and_dns_deadline():
    module = load_proxy_module()
    route = module._EgressRoute("proxy", "http://proxy.example")
    assert route.proxy_port == 80, route.proxy_port
    try:
        module._EgressRoute("proxy", "http://secret-user:secret-pass@proxy.example")
    except ValueError as exc:
        message = str(exc)
        assert "secret-user" not in message and "secret-pass" not in message, message
    else:
        raise AssertionError("authenticated proxy URL should be rejected")

    print("EGRESS VALIDATION PASS: standard proxy port and redacted errors")


def main():
    test_route_validation_and_dns_deadline()
    with tempfile.TemporaryDirectory(prefix="dsvision-egress-") as tmp_name:
        tmp = Path(tmp_name)
        cert, key = create_test_certificate(tmp)
        upstream = start_tls_upstream(cert, key)
        SERVERS.append(upstream)
        upstream_port = upstream.server_address[1]

        # Default direct egress ignores ambient proxy environment variables.
        direct_port = free_port()
        direct_proc, direct_log = start_proxy(
            tmp, direct_port, f"https://localhost:{upstream_port}", cert)
        PROCESSES.append(direct_proc)
        wait_listen(direct_port, direct_proc)
        status, _ = post(direct_port)
        assert status == 200, status
        direct_text = read_log(direct_log)
        assert "egress route OK: direct" in direct_text, direct_text
        assert "egress route failed" not in direct_text, direct_text
        print("EGRESS DIRECT PASS: ambient proxy settings are ignored")

        refused_port = free_port()
        connect_proxy = start_connect_proxy(upstream_port, refused_port)
        SERVERS.append(connect_proxy)
        proxy_url = f"http://127.0.0.1:{connect_proxy.server_address[1]}"

        # Both routes fail: the client gets one safe reason per route.
        dead_proxy_port = free_port()
        fail_port = free_port()
        fail_proc, fail_log = start_proxy(
            tmp, fail_port, f"https://127.0.0.1:{refused_port}", cert,
            "--upstream-proxy", f"http://127.0.0.1:{dead_proxy_port}")
        PROCESSES.append(fail_proc)
        wait_listen(fail_port, fail_proc)
        status, data = post(fail_port)
        text = data.decode(errors="replace")
        assert status == 502, (status, text)
        assert "All egress routes failed: direct ->" in text, text
        assert f"proxy http://127.0.0.1:{dead_proxy_port} ->" in text, text
        print("EGRESS ALL-FAIL PASS: 502 lists every explicit route")

        # Direct fails, CONNECT+TLS succeeds, and the successful route becomes sticky.
        failover_port = free_port()
        failover_proc, failover_log = start_proxy(
            tmp, failover_port, f"https://127.0.0.1:{refused_port}", cert,
            "--upstream-proxy", proxy_url)
        PROCESSES.append(failover_proc)
        wait_listen(failover_port, failover_proc)
        body = b'{"model":"deepseek-chat","input":"exact body"}'
        auth = "Bearer existing-codex-key"
        status, _ = post(failover_port, body=body, headers={"Authorization": auth})
        assert status == 200, status
        status, _ = post(failover_port)
        assert status == 200, status
        failover_text = read_log(failover_log)
        assert failover_text.count("egress route failed: direct") == 1, failover_text
        assert failover_text.count(f"egress route OK: proxy {proxy_url}") == 2, failover_text
        record = UpstreamHandler.records[-2]
        assert record["body"] == body, record
        assert record["headers"].get("Authorization") == auth, record
        assert ConnectProxyHandler.authorities[-2:] == [
            f"127.0.0.1:{refused_port}", f"127.0.0.1:{refused_port}",
        ], ConnectProxyHandler.authorities
        print("EGRESS FAILOVER PASS: CONNECT+TLS, auth, body, and sticky routing preserved")

        # HTTP responses do not trigger route switching.
        proxy_first_port = free_port()
        proxy_first_proc, proxy_first_log = start_proxy(
            tmp, proxy_first_port, f"https://127.0.0.1:{refused_port}", cert,
            "--upstream-proxy", proxy_url, "--proxy-first")
        PROCESSES.append(proxy_first_proc)
        wait_listen(proxy_first_port, proxy_first_proc)
        status, data = post(proxy_first_port, path="/status")
        assert status == 503, (status, data)
        proxy_first_text = read_log(proxy_first_log)
        assert "egress route failed" not in proxy_first_text, proxy_first_text
        assert f"egress route OK: proxy {proxy_url}" in proxy_first_text, proxy_first_text
        print("EGRESS STATUS PASS: HTTP 503 passes through without failover")

        # SSE remains incremental after failover rather than being buffered.
        conn = http.client.HTTPConnection("127.0.0.1", failover_port, timeout=8)
        conn.request("POST", "/stream", body=b"{}", headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        first = response.read(18)
        STREAM_RELEASE.set()
        rest = response.read()
        conn.close()
        assert response.status == 200, response.status
        assert first == b'data: {"part":1}\n\n', first
        assert STREAM_RELEASED.wait(timeout=1), "upstream timed out before client released it"
        assert b'data: {"part":2}\n\n' in rest, rest
        print("EGRESS SSE PASS: first event is forwarded incrementally")

        for proc in reversed(PROCESSES):
            stop_process(proc)
        PROCESSES.clear()
        for server in reversed(SERVERS):
            server.shutdown()
            server.server_close()
        SERVERS.clear()

    print("EGRESS SMOKE PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        # Best-effort cleanup when an assertion interrupts the normal path.
        for process in reversed(PROCESSES):
            stop_process(process)
        for server in reversed(SERVERS):
            server.shutdown()
            server.server_close()
