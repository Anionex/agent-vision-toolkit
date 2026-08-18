#!/usr/bin/env python3
"""Unit test: pixel_diff compositing, ranking, and CLI output."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "skills", "vision-skills", "scripts", "pixel_diff.py")


def main():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("SKIP: Pillow not installed; pixel_diff is an optional feature")
        return

    spec = importlib.util.spec_from_loader(
        "pixel_diff_mod", importlib.machinery.SourceFileLoader("pixel_diff_mod", SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with tempfile.TemporaryDirectory() as raw:
        original = os.path.join(raw, "a.png")
        corrupted = os.path.join(raw, "b.png")
        transparent = os.path.join(raw, "t.png")
        base = Image.new("RGB", (240, 120), "white")
        base.save(original)
        broken = base.copy()
        ImageDraw.Draw(broken).rectangle((180, 0, 240, 60), fill="black")
        broken.save(corrupted)
        Image.new("RGBA", (240, 120), (0, 0, 0, 0)).save(transparent)

        from pathlib import Path
        flat = mod.load(Path(transparent))
        assert flat.getpixel((10, 10)) == (255, 255, 255), \
            "transparency must composite on white, not read as black"
        print("PASS: transparent pixels composite to white")

        result = subprocess.run(
            [sys.executable, SCRIPT, original, corrupted, "--grid", "4", "--top", "1"],
            text=True, capture_output=True, check=True)
        assert "overall difference:" in result.stdout
        top_line = result.stdout.strip().splitlines()[-1]
        assert "x1: 180" in top_line and "100.00%" in top_line, top_line
        print("PASS: worst region ranking points at the corrupted cell")

        clean = subprocess.run(
            [sys.executable, SCRIPT, original, transparent, "--top", "1"],
            text=True, capture_output=True, check=True)
        assert "overall difference: 0.00%" in clean.stdout, clean.stdout
        print("PASS: transparent rebuild diffs as blank, not black")


if __name__ == "__main__":
    main()
