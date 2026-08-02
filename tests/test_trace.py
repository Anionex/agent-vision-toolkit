#!/usr/bin/env python3
"""Unit test: trace post-processing; full CLI run when vtracer is available."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_trace():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "trace")
    spec = importlib.util.spec_from_loader(
        "trace_cli", importlib.machinery.SourceFileLoader("trace_cli", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    mod = _load_trace()

    svg = ('<svg><path d="M0,0 L9,0 Z" fill="#FFFFFF" transform="x"/>'
           '<path d="M1.23456,7.891011 L2,3" fill="#000000"/></svg>')
    stripped = mod.strip_background(svg)
    assert 'fill="#FFFFFF"' not in stripped, "leading white background path must be dropped"
    assert 'fill="#000000"' in stripped

    kept = mod.strip_background('<svg><path d="M0,0" fill="#000000"/></svg>')
    assert 'fill="#000000"' in kept, "non-white first path must survive"

    truncated = mod.truncate_decimals(stripped)
    assert "1.23456" not in truncated and "1.23" in truncated
    assert "7.891011" not in truncated and "7.89" in truncated
    print("PASS: background stripping and decimal truncation")

    try:
        import vtracer  # noqa: F401
        from PIL import Image
    except ImportError:
        print("SKIP: vtracer/Pillow not installed; CLI run is an optional feature")
        return

    with tempfile.TemporaryDirectory() as raw:
        src = os.path.join(raw, "boxes.png")
        image = Image.new("RGB", (120, 60), "white")
        for x in range(20, 100):
            for y in range(15, 45):
                image.putpixel((x, y), (0, 0, 0))
        image.save(src)
        out = os.path.join(raw, "boxes.svg")
        cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "trace")
        result = subprocess.run([sys.executable, cli, src, "--polygon", "-o", out],
                                text=True, capture_output=True, check=True)
        svg = open(out).read()
        assert "<path" in svg and 'fill="#FFFFFF"' not in svg
        assert "paths" in result.stdout
        print("PASS: trace CLI produces cleaned SVG")


if __name__ == "__main__":
    main()
