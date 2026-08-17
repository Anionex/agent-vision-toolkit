#!/usr/bin/env python3
"""Screenshot an HTML file with headless Chrome/Chromium/Edge.

The default path intentionally remains the small Chrome CLI wrapper used by
the original upstream tool. ``--full-page`` uses Chrome DevTools Protocol
instead: the requested viewport remains the layout viewport while the page's
CSS scroll height is measured and captured in one pass.
"""

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


CHROME_CANDIDATES = (
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "brave-browser",
)

FULL_PAGE_TIMEOUT_SECONDS = 30.0
FULL_PAGE_MAX_GROWTH_ROUNDS = 25
FULL_PAGE_MAX_SCROLL_STEPS = 2000


def find_chrome() -> str | None:
    for candidate in CHROME_CANDIDATES:
        path = shutil.which(candidate)
        if path:
            return path
        if candidate.startswith("/") and Path(candidate).is_file():
            return candidate
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if not base:
            continue
        for sub in ("Google/Chrome/Application/chrome.exe",
                    "Microsoft/Edge/Application/msedge.exe"):
            path = Path(base) / sub
            if path.is_file():
                return str(path)
    return None


def default_output(source: str) -> str:
    if source.startswith(("http://", "https://", "file://", "data:")):
        stem = Path(urlparse(source).path).stem
        return f"{stem or 'page'}.png"
    return f"{Path(source).stem}.png"


def read_http_json(port: int, path: str) -> object:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=1.0) as response:
        return json.loads(response.read().decode("utf-8"))


class DevToolsSocket:
    """Minimal RFC 6455 client for the Chrome DevTools Protocol."""

    def __init__(self, websocket_url: str):
        parsed = urlparse(websocket_url)
        if parsed.scheme != "ws" or parsed.hostname is None or parsed.port is None:
            raise RuntimeError("invalid DevTools websocket URL")
        self.socket = socket.create_connection((parsed.hostname, parsed.port), timeout=5.0)
        self.socket.settimeout(5.0)
        self.buffer = bytearray()
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {parsed.path or '/'} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii")
        self.socket.sendall(request)
        response = self._read_until(b"\r\n\r\n")
        if not response.startswith(b"HTTP/1.1 101"):
            raise RuntimeError("Chrome did not accept the DevTools websocket")
        expected_accept = base64.b64encode(hashlib.sha1(
            f"{key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11".encode("ascii")
        ).digest()).decode("ascii")
        headers = response.decode("latin-1").split("\r\n")
        accept = next((line.split(":", 1)[1].strip() for line in headers
                       if line.lower().startswith("sec-websocket-accept:")), None)
        if accept != expected_accept:
            raise RuntimeError("Chrome returned an invalid DevTools websocket handshake")
        self.next_id = 0

    def _read_until(self, marker: bytes) -> bytes:
        data = bytearray()
        while marker not in data:
            chunk = self.socket.recv(4096)
            if not chunk:
                raise RuntimeError("DevTools websocket closed during handshake")
            data.extend(chunk)
        boundary = data.index(marker) + len(marker)
        self.buffer.extend(data[boundary:])
        return bytes(data[:boundary])

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        length = len(masked)
        if length < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | length)
        elif length < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, length)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, length)
        self.socket.sendall(header + mask + masked)

    def _read_frame(self) -> tuple[bool, int, bytes]:
        header = self._read_exact(2)
        first, second = header
        final = (first & 0x80) != 0
        opcode = first & 0x0F
        length = second & 0x7F
        masked = (second & 0x80) != 0
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else None
        payload = self._read_exact(length)
        if mask is not None:
            payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        return final, opcode, payload

    def _read_message(self) -> tuple[int, bytes]:
        fragments: list[bytes] = []
        message_opcode: int | None = None
        while True:
            final, opcode, payload = self._read_frame()
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise RuntimeError("DevTools websocket closed")
            if opcode in (0x1, 0x2):
                fragments = [payload]
                message_opcode = opcode
            elif opcode == 0x0 and message_opcode is not None:
                fragments.append(payload)
            else:
                continue
            if final and message_opcode is not None:
                return message_opcode, b"".join(fragments)

    def _read_exact(self, length: int) -> bytes:
        data = bytearray()
        if self.buffer:
            take = min(length, len(self.buffer))
            data.extend(self.buffer[:take])
            del self.buffer[:take]
        while len(data) < length:
            chunk = self.socket.recv(length - len(data))
            if not chunk:
                raise RuntimeError("DevTools websocket closed unexpectedly")
            data.extend(chunk)
        return bytes(data)

    def command(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        request_id = self.next_id
        request = {"id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        self._send_frame(0x1, json.dumps(request, separators=(",", ":")).encode("utf-8"))
        while True:
            opcode, payload = self._read_message()
            if opcode != 0x1:
                continue
            message = json.loads(payload.decode("utf-8"))
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"{method}: {message['error'].get('message', 'CDP command failed')}")
            return message.get("result", {})

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.socket.close()


def evaluate(client: DevToolsSocket, expression: str) -> object:
    result = client.command("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    })
    if "exceptionDetails" in result:
        raise RuntimeError(result["exceptionDetails"].get("text", "Runtime.evaluate failed"))
    remote = result.get("result", {})
    if remote.get("subtype") == "error":
        raise RuntimeError(remote.get("description", "Runtime.evaluate failed"))
    return remote.get("value")


def wait_for_target(port: int, deadline: float) -> dict:
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            targets = read_http_json(port, "/json/list")
            if isinstance(targets, list):
                for target in targets:
                    if (isinstance(target, dict) and target.get("type") == "page"
                            and target.get("webSocketDebuggerUrl")):
                        return target
        except (OSError, URLError, ValueError) as error:
            last_error = error
        time.sleep(0.05)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for Chrome DevTools{detail}")


def wait_for_devtools_port(profile: Path, process: subprocess.Popen,
                           deadline: float) -> int:
    active_port = profile / "DevToolsActivePort"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Chrome exited before DevTools was ready (code {process.returncode})")
        try:
            lines = active_port.read_text().splitlines()
            port = int(lines[0])
            if 0 < port <= 65535:
                return port
        except (OSError, ValueError, IndexError) as error:
            last_error = error
        time.sleep(0.05)
    detail = f": {last_error}" if last_error else ""
    raise RuntimeError(f"timed out waiting for Chrome DevTools port{detail}")


def wait_for_ready(client: DevToolsSocket, deadline: float) -> None:
    while time.monotonic() < deadline:
        if evaluate(client, "document.readyState") == "complete":
            return
        time.sleep(0.05)
    raise RuntimeError("timed out waiting for the HTML document")


def pause_for_frame(seconds: float) -> None:
    time.sleep(max(0.02, seconds))


def build_full_page_command(chrome: str, source: str, profile: Path,
                            width: int, height: int, scale: int) -> list[str]:
    command = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check", "--use-mock-keychain",
        "--blink-settings=imagesLazyLoadingEnabled=false",
        f"--window-size={width},{height}",
        "--remote-debugging-port=0",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={profile}",
    ]
    if scale != 1:
        command.append(f"--force-device-scale-factor={scale}")
    command.append(source)
    return command


def measure_page_height(client: DevToolsSocket) -> int:
    return int(evaluate(client, """
        Math.max(document.documentElement.scrollHeight,
                 document.body ? document.body.scrollHeight : 0)
    """) or 0)


def enforce_pixel_limit(width: int, page_height: int, scale: int,
                        max_pixels: int | None) -> None:
    if page_height <= 0:
        raise RuntimeError("document has no measurable scroll height")
    output_pixels = width * page_height * scale * scale
    if max_pixels is not None and output_pixels > max_pixels:
        raise RuntimeError(
            f"full-page screenshot would exceed --max-pixels "
            f"({output_pixels} > {max_pixels})"
        )


def ensure_before_deadline(deadline: float, message: str) -> None:
    if time.monotonic() >= deadline:
        raise RuntimeError(message)


def settle_full_page(client: DevToolsSocket, width: int, height: int, scale: int,
                     max_pixels: int | None, deadline: float) -> int:
    page_height = measure_page_height(client)
    enforce_pixel_limit(width, page_height, scale, max_pixels)
    scan_start = 0
    growth_rounds = 0
    scroll_steps = 0
    waited_for_images = False

    while True:
        ensure_before_deadline(deadline, "timed out while stabilizing the full page")
        measured_before_sweep = page_height
        for position in range(scan_start, measured_before_sweep, max(1, height)):
            scroll_steps += 1
            if scroll_steps > FULL_PAGE_MAX_SCROLL_STEPS:
                raise RuntimeError("full page requires too many scroll steps to capture safely")
            ensure_before_deadline(deadline, "timed out while scrolling the full page")
            evaluate(client, f"window.scrollTo(0, {position}); true")
            pause_for_frame(0.12)
        evaluate(client, f"window.scrollTo(0, {measured_before_sweep}); true")
        pause_for_frame(0.12)

        measured_after_sweep = measure_page_height(client)
        enforce_pixel_limit(width, measured_after_sweep, scale, max_pixels)
        if measured_after_sweep != measured_before_sweep:
            growth_rounds += 1
            if growth_rounds > FULL_PAGE_MAX_GROWTH_ROUNDS:
                raise RuntimeError("page is still changing after repeated full-page sweeps")
            scan_start = (max(0, measured_before_sweep - height)
                          if measured_after_sweep > measured_before_sweep else 0)
            page_height = measured_after_sweep
            waited_for_images = False
            continue

        if not waited_for_images:
            evaluate(client, """
                Promise.race([
                  Promise.all(Array.from(document.images)
                    .filter(image => !image.complete)
                    .map(image => new Promise(resolve => {
                      image.addEventListener('load', resolve, {once: true});
                      image.addEventListener('error', resolve, {once: true});
                    }))),
                  new Promise(resolve => setTimeout(resolve, 3000))
                ]).then(() => true)
            """)
            waited_for_images = True
            ensure_before_deadline(deadline, "timed out while waiting for full-page images")
            measured_after_images = measure_page_height(client)
            enforce_pixel_limit(width, measured_after_images, scale, max_pixels)
            if measured_after_images != page_height:
                growth_rounds += 1
                if growth_rounds > FULL_PAGE_MAX_GROWTH_ROUNDS:
                    raise RuntimeError("page is still changing after image loading")
                scan_start = (max(0, page_height - height)
                              if measured_after_images > page_height else 0)
                page_height = measured_after_images
                waited_for_images = False
                continue

        evaluate(client, "window.scrollTo(0, 0); true")
        pause_for_frame(0.5)
        final_height = measure_page_height(client)
        enforce_pixel_limit(width, final_height, scale, max_pixels)
        if final_height == page_height:
            return final_height
        growth_rounds += 1
        if growth_rounds > FULL_PAGE_MAX_GROWTH_ROUNDS:
            raise RuntimeError("page is still changing before full-page capture")
        scan_start = max(0, page_height - height) if final_height > page_height else 0
        page_height = final_height
        waited_for_images = False


def capture_full_page(chrome: str, source: str, output: Path, width: int, height: int,
                      scale: int, wait_ms: int, max_pixels: int | None) -> int:
    profile = Path(tempfile.mkdtemp(prefix="agent-vision-html-shot-"))
    process: subprocess.Popen | None = None
    client: DevToolsSocket | None = None
    try:
        command = build_full_page_command(chrome, source, profile, width, height, scale)
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        startup_deadline = time.monotonic() + 15.0
        port = wait_for_devtools_port(profile, process, startup_deadline)
        target = wait_for_target(port, startup_deadline)
        client = DevToolsSocket(str(target["webSocketDebuggerUrl"]))
        client.command("Page.enable")
        client.command("Runtime.enable")
        client.command("Emulation.setDeviceMetricsOverride", {
            "width": width,
            "height": height,
            "deviceScaleFactor": scale,
            "mobile": False,
            "screenWidth": width,
            "screenHeight": height,
        })
        client.command("Page.navigate", {"url": source})
        wait_for_ready(client, time.monotonic() + 15.0)
        if wait_ms > 0:
            pause_for_frame(wait_ms / 1000.0)

        # Keep the requested viewport fixed. Scrolling, rather than growing
        # the viewport, wakes IO/reveal handlers without changing vh/svh.
        evaluate(client, """
            (() => {
              document.documentElement.style.scrollBehavior = 'auto';
              if (document.body) document.body.style.scrollBehavior = 'auto';
              window.scrollTo(0, 0);
              return true;
            })()
        """)
        page_height = settle_full_page(
            client, width, height, scale, max_pixels,
            time.monotonic() + FULL_PAGE_TIMEOUT_SECONDS,
        )
        result = client.command("Page.captureScreenshot", {
            "format": "png",
            "fromSurface": True,
            "captureBeyondViewport": True,
            "clip": {"x": 0, "y": 0, "width": width, "height": page_height, "scale": 1},
        })
        data = result.get("data")
        if not isinstance(data, str):
            raise RuntimeError("Chrome did not return screenshot data")
        output.write_bytes(base64.b64decode(data))
        return page_height
    finally:
        if client is not None:
            client.close()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="html_shot",
        description="Screenshot an HTML file (or URL) to PNG with headless Chrome/Chromium/Edge",
    )
    parser.add_argument("source", help="path to a local .html file, or an http(s):// URL")
    parser.add_argument("-o", "--output", help="output PNG path (default: <source-stem>.png in the current directory)")
    parser.add_argument("--width", type=int, default=1280, help="viewport width in CSS pixels (default: 1280)")
    parser.add_argument("--height", type=int, default=800, help="viewport height in CSS pixels (default: 800)")
    parser.add_argument("--scale", type=int, default=1,
                        help="device scale factor: 2 makes the PNG 2x for small text (default: 1)")
    parser.add_argument("--wait-ms", type=int, default=0,
                        help="wait time in ms before capturing (default: 0, capture immediately)")
    parser.add_argument("--full-page", action="store_true",
                        help="capture the full CSS scroll height while keeping the requested viewport")
    parser.add_argument("--max-pixels", type=int,
                        help="reject full-page captures larger than this many output pixels")
    args = parser.parse_args()

    chrome = find_chrome()
    if not chrome:
        parser.exit(1, "html_shot: no Chrome/Chromium/Edge found; install one and retry\n")

    source = args.source
    if not source.startswith(("http://", "https://", "file://", "data:")):
        path = Path(source).expanduser()
        if not path.is_file():
            parser.exit(1, f"html_shot: file not found: {path}\n")
        source = path.resolve().as_uri()

    output = Path(args.output).expanduser().resolve() if args.output else Path(default_output(source)).resolve()
    if args.full_page:
        try:
            page_height = capture_full_page(
                chrome, source, output, args.width, args.height,
                args.scale, args.wait_ms, args.max_pixels,
            )
        except Exception as error:
            parser.exit(1, f"html_shot: full-page capture failed: {error}\n")
        print(f"wrote {output} ({args.width * args.scale}x{page_height * args.scale}; pageHeight={page_height})")
        return

    command = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--no-first-run", "--no-default-browser-check",
        f"--window-size={args.width},{args.height}",
        f"--screenshot={output}",
    ]
    if args.scale != 1:
        command.append(f"--force-device-scale-factor={args.scale}")
    if args.wait_ms > 0:
        command.append(f"--virtual-time-budget={args.wait_ms}")
    command.append(source)

    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0 or not output.is_file():
        message = result.stderr.strip() or result.stdout.strip() or f"chrome exited with code {result.returncode}"
        parser.exit(1, f"html_shot: capture failed: {message}\n")
    print(f"wrote {output} ({args.width * args.scale}x{args.height * args.scale})")


if __name__ == "__main__":
    main()
