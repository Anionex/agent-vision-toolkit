#!/usr/bin/env python3
"""Focused tests for the html_shot case script (HTML file -> PNG).

The CLI half needs a Chrome-family browser; when none is found it is
skipped, matching the optional-tool convention of the other CLIs.
"""

import importlib.machinery
import importlib.util
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                      "skills", "vision-tools", "scripts", "html_shot.py")


def _load_html_shot():
    spec = importlib.util.spec_from_loader(
        "html_shot_cli", importlib.machinery.SourceFileLoader("html_shot_cli", SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _png_size(path):
    with open(path, "rb") as handle:
        header = handle.read(24)
    assert header[:8] == b"\x89PNG\r\n\x1a\n"
    assert header[12:16] == b"IHDR"
    return struct.unpack("!II", header[16:24])


def test_chrome_discovery():
    chrome = _load_html_shot().find_chrome()
    if chrome is None:
        print("SKIP: no Chrome-family browser found; CLI run is optional")
        return False
    assert os.path.isfile(chrome) or chrome in (
        "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
        "microsoft-edge", "brave-browser"), chrome
    return True


def test_default_output_naming():
    mod = _load_html_shot()
    assert mod.default_output("page.html") == "page.png"
    assert mod.default_output("/tmp/a/b/page.html") == "page.png"
    assert mod.default_output("https://example.com/foo/bar") == "bar.png"
    assert mod.default_output("https://example.com") == "page.png"


def test_full_page_command_isolated():
    mod = _load_html_shot()
    profile = Path("disposable-profile")
    command = mod.build_full_page_command(
        "chrome", profile, 1280, 800, 2,
    )
    assert "--use-mock-keychain" in command
    assert "--remote-debugging-port=0" in command
    assert f"--user-data-dir={profile}" in command
    assert "--force-device-scale-factor=2" in command
    assert command[-1] == "about:blank"
    assert not any(arg.startswith("--remote-debugging-port=") and arg != "--remote-debugging-port=0"
                   for arg in command)


def _server_frame(payload, opcode=0x1, final=True):
    first = (0x80 if final else 0) | opcode
    length = len(payload)
    if length < 126:
        return struct.pack("!BB", first, length) + payload
    if length < 65536:
        return struct.pack("!BBH", first, 126, length) + payload
    return struct.pack("!BBQ", first, 127, length) + payload


def _recv_exact(connection, length):
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise AssertionError("socket closed before the expected test frame arrived")
        data.extend(chunk)
    return bytes(data)


def test_websocket_frame_codec():
    mod = _load_html_shot()
    client_socket, server_socket = socket.socketpair()
    client = mod.DevToolsSocket.__new__(mod.DevToolsSocket)
    client.socket = client_socket
    client.buffer = bytearray()
    try:
        payload = b"x" * 130
        server_socket.sendall(_server_frame(payload))
        assert client._read_frame() == (True, 0x1, payload)

        server_socket.sendall(
            _server_frame(b"hel", final=False)
            + _server_frame(b"ping", opcode=0x9)
            + _server_frame(b"lo", opcode=0x0)
        )
        assert client._read_message() == (0x1, b"hello")
        pong = _recv_exact(server_socket, 10)
        assert pong[0] == 0x8A and pong[1] & 0x80

        client._send_frame(0x1, b"masked")
        header = _recv_exact(server_socket, 2)
        assert header[0] == 0x81 and header[1] & 0x80
        length = header[1] & 0x7F
        mask = _recv_exact(server_socket, 4)
        masked = _recv_exact(server_socket, length)
        assert bytes(value ^ mask[index % 4]
                     for index, value in enumerate(masked)) == b"masked"
    finally:
        client_socket.close()
        server_socket.close()


def test_cli_screenshot():
    with tempfile.TemporaryDirectory() as temp_dir:
        html = os.path.join(temp_dir, "probe.html")
        with open(html, "w") as handle:
            handle.write("<!doctype html><html><body style=\"margin:0;background:#f0f0f0\">"
                         "<h1>probe</h1></body></html>")
        output = os.path.join(temp_dir, "out.png")
        result = subprocess.run([sys.executable, SCRIPT, html, "--width", "320", "--height", "200",
                                 "-o", output], text=True, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        assert os.path.isfile(output)
        assert _png_size(output) == (320, 200)


def test_cli_default_output_in_cwd():
    with tempfile.TemporaryDirectory() as temp_dir:
        html = os.path.join(temp_dir, "probe.html")
        with open(html, "w") as handle:
            handle.write("<!doctype html><html><body style=\"margin:0;background:#fff\">"
                         "<p>hi</p></body></html>")
        result = subprocess.run([sys.executable, SCRIPT, html, "--width", "200", "--height", "100"],
                                cwd=temp_dir, text=True, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        assert os.path.isfile(os.path.join(temp_dir, "probe.png"))


def test_cli_missing_file_error():
    with tempfile.TemporaryDirectory() as temp_dir:
        result = subprocess.run([sys.executable, SCRIPT, os.path.join(temp_dir, "nope.html")],
                                text=True, capture_output=True, timeout=30)
        assert result.returncode != 0 and "not found" in result.stderr


def test_cli_full_page_keeps_layout_viewport():
    with tempfile.TemporaryDirectory() as temp_dir:
        html = os.path.join(temp_dir, "full-page.html")
        with open(html, "w") as handle:
            handle.write(
                "<!doctype html><html><head><style>"
                "html,body{margin:0}"
                ".viewport{height:100vh;background:#ff0000}"
                ".tail{height:240px;background:#0000ff}"
                "</style></head><body>"
                '<div class="viewport"></div><div class="tail"></div>'
                "</body></html>"
            )
        output = os.path.join(temp_dir, "full-page.png")
        result = subprocess.run([
            sys.executable, SCRIPT, html,
            "--width", "320", "--height", "200", "--scale", "2",
            "--full-page", "--max-pixels", "1000000", "-o", output,
        ], text=True, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        assert "pageHeight=440" in result.stdout
        assert _png_size(output) == (640, 880)


def test_cli_full_page_max_pixels_guard():
    with tempfile.TemporaryDirectory() as temp_dir:
        html = os.path.join(temp_dir, "too-tall.html")
        with open(html, "w") as handle:
            handle.write(
                "<!doctype html><html><body style=\"margin:0;height:50000px\"></body></html>"
            )
        output = os.path.join(temp_dir, "blocked.png")
        started = time.monotonic()
        result = subprocess.run([
            sys.executable, SCRIPT, html,
            "--width", "320", "--height", "200", "--full-page",
            "--max-pixels", "1000", "-o", output,
        ], text=True, capture_output=True, timeout=30)
        elapsed = time.monotonic() - started
        assert result.returncode != 0
        assert "exceed --max-pixels" in result.stderr
        assert not os.path.exists(output)
        assert elapsed < 5, f"pixel guard rejected too slowly: {elapsed:.2f}s"


def test_cli_full_page_stabilizes_incremental_growth():
    with tempfile.TemporaryDirectory() as temp_dir:
        html = os.path.join(temp_dir, "incremental.html")
        with open(html, "w") as handle:
            handle.write(
                "<!doctype html><html><head><style>"
                "html,body{margin:0}.block{height:200px}"
                ".block:nth-of-type(odd){background:#ff0000}"
                ".block:nth-of-type(even){background:#0000ff}"
                "</style></head><body><script>"
                "let count=0;"
                "function add(){const node=document.createElement('div');"
                "node.className='block';document.body.appendChild(node);count++;}"
                "add();add();"
                "let loading=false;"
                "addEventListener('scroll',()=>{"
                "if(!loading && count<10 && "
                "scrollY+innerHeight>=document.documentElement.scrollHeight-1){"
                "loading=true;setTimeout(()=>{"
                "for(let i=0;i<4 && count<10;i++)add();loading=false;"
                "},1000);}});"
                "</script></body></html>"
            )
        output = os.path.join(temp_dir, "incremental.png")
        result = subprocess.run([
            sys.executable, SCRIPT, html,
            "--width", "320", "--height", "200", "--full-page",
            "--max-pixels", "1000000", "-o", output,
        ], text=True, capture_output=True, timeout=30)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        assert "pageHeight=2000" in result.stdout
        assert _png_size(output) == (320, 2000)


class CountingHandler(BaseHTTPRequestHandler):
    paths = []

    def do_GET(self):
        CountingHandler.paths.append(self.path)
        body = (b"<!doctype html><html><body style='margin:0;height:400px'>"
                b"single navigation</body></html>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def test_cli_full_page_loads_url_once():
    server = HTTPServer(("127.0.0.1", 0), CountingHandler)
    CountingHandler.paths = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = os.path.join(temp_dir, "url.png")
            source = f"http://127.0.0.1:{server.server_port}/page"
            result = subprocess.run([
                sys.executable, SCRIPT, source,
                "--width", "320", "--height", "200", "--full-page",
                "--max-pixels", "1000000", "-o", output,
            ], text=True, capture_output=True, timeout=30)
            if result.returncode != 0:
                raise AssertionError(result.stderr)
            assert _png_size(output) == (320, 400)
            assert CountingHandler.paths.count("/page") == 1, CountingHandler.paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    test_default_output_naming()
    test_full_page_command_isolated()
    test_websocket_frame_codec()
    test_cli_missing_file_error()
    if test_chrome_discovery():
        test_cli_screenshot()
        test_cli_default_output_in_cwd()
        test_cli_full_page_keeps_layout_viewport()
        test_cli_full_page_max_pixels_guard()
        test_cli_full_page_stabilizes_incremental_growth()
        test_cli_full_page_loads_url_once()
    print("HTML SHOT TEST PASS")


if __name__ == "__main__":
    main()
