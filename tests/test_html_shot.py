#!/usr/bin/env python3
"""Focused tests for the html_shot case script (HTML file -> PNG).

The CLI half needs a Chrome-family browser; when none is found it is
skipped, matching the optional-tool convention of the other CLIs.
"""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                      "skills", "vision-tools", "scripts", "html_shot.py")


def _load_html_shot():
    spec = importlib.util.spec_from_loader(
        "html_shot_cli", importlib.machinery.SourceFileLoader("html_shot_cli", SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def test_cli_screenshot():
    try:
        from PIL import Image
    except ImportError:
        print("SKIP: Pillow not installed; cannot verify the PNG")
        return
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
        with Image.open(output) as shot:
            assert shot.size == (320, 200)


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
    try:
        from PIL import Image
    except ImportError:
        print("SKIP: Pillow not installed; cannot verify the full-page PNG")
        return
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
        with Image.open(output) as shot:
            assert shot.size == (640, 880)
            assert shot.getpixel((20, 398))[:3] == (255, 0, 0)
            assert shot.getpixel((20, 402))[:3] == (0, 0, 255)


def test_cli_full_page_max_pixels_guard():
    with tempfile.TemporaryDirectory() as temp_dir:
        html = os.path.join(temp_dir, "too-tall.html")
        with open(html, "w") as handle:
            handle.write(
                "<!doctype html><html><body style=\"margin:0;height:1000px\"></body></html>"
            )
        output = os.path.join(temp_dir, "blocked.png")
        result = subprocess.run([
            sys.executable, SCRIPT, html,
            "--width", "320", "--height", "200", "--full-page",
            "--max-pixels", "1000", "-o", output,
        ], text=True, capture_output=True, timeout=30)
        assert result.returncode != 0
        assert "exceed --max-pixels" in result.stderr
        assert not os.path.exists(output)


def main():
    test_default_output_naming()
    test_cli_missing_file_error()
    if test_chrome_discovery():
        test_cli_screenshot()
        test_cli_default_output_in_cwd()
        test_cli_full_page_keeps_layout_viewport()
        test_cli_full_page_max_pixels_guard()
    print("HTML SHOT TEST PASS")


if __name__ == "__main__":
    main()
