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
                                 "-o", output], text=True, capture_output=True)
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
                                cwd=temp_dir, text=True, capture_output=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr)
        assert os.path.isfile(os.path.join(temp_dir, "probe.png"))


def test_cli_missing_file_error():
    with tempfile.TemporaryDirectory() as temp_dir:
        result = subprocess.run([sys.executable, SCRIPT, os.path.join(temp_dir, "nope.html")],
                                text=True, capture_output=True)
        assert result.returncode != 0 and "not found" in result.stderr


def main():
    test_default_output_naming()
    test_cli_missing_file_error()
    if test_chrome_discovery():
        test_cli_screenshot()
        test_cli_default_output_in_cwd()
    print("HTML SHOT TEST PASS")


if __name__ == "__main__":
    main()
