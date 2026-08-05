#!/usr/bin/env python3
"""html_shot: one-command HTML file (or URL) -> PNG screenshot.

The render loop for rebuild work: write HTML, screenshot it, pixel_diff it
against the design image. Rendering happens in a real headless
Chrome/Chromium/Edge, so the shot shows what a browser actually renders —
no Python rendering stack, no dependencies beyond a Chrome-family browser
and the stdlib.

Only the viewport is captured; pass --height (and --scale for HiDPI)
when the page is taller than the default window. Local HTML files and
http(s):// URLs both work.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

CHROME_CANDIDATES = (
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "brave-browser",
)


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
                        help="virtual time budget in ms before capturing (default: 0, capture immediately)")
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
