#!/usr/bin/env python3
"""Focused tests for extract_fg.py (manual region + auto icon modes)."""

import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image


def _make_badge(size=(200, 200), disc_r=60):
    """Synthetic badge: light-blue disc + white ring + deep-blue glyph + dark text noise."""
    w, h = size
    img = Image.new("RGB", size, (234, 241, 249))  # background
    cx, cy = w // 2, h // 2
    px = img.load()
    for y in range(h):
        for x in range(w):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d <= disc_r:
                px[x, y] = (180, 211, 240)          # disc (light blue)
            elif d <= disc_r + 4:
                px[x, y] = (255, 255, 255)          # white ring
            if d <= 20:
                px[x, y] = (47, 95, 191)            # glyph (deep blue)
    # dark text-like noise far from the disc (must NOT leak into auto output)
    for y in range(h - 20, h - 8):
        for x in range(w - 30, w - 15):
            px[x, y] = (85, 85, 85)
    return img


def _cli():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                        "skills", "vision-tools", "scripts", "extract_fg.py")


def _run(*args, check=True):
    return subprocess.run([sys.executable, _cli(), *args],
                          text=True, capture_output=True, check=check)


def _assert_glyph_only(clean):
    assert os.path.isfile(clean), f"missing {clean}"
    a = np.asarray(Image.open(clean).convert("RGBA"))
    fg = a[:, :, 3] > 128
    assert fg.sum() > 200, f"too little foreground: {fg.sum()}"
    rgb = a[:, :, :3][fg].astype(int)
    sat = rgb.max(1) - rgb.min(1)
    deep_blue = (rgb[:, 2] > rgb[:, 0] + 40) & (sat > 60)
    assert deep_blue.mean() > 0.85, f"glyph share too low: {deep_blue.mean():.2f}"
    disc_like = (np.abs(rgb[:, 0] - 180) < 30) & (np.abs(rgb[:, 1] - 211) < 30)
    assert disc_like.mean() < 0.05, f"disc residue too high: {disc_like.mean():.2f}"
    dark_gray = (np.abs(rgb[:, 0] - 85) < 25) & (np.abs(rgb[:, 1] - 85) < 25)
    assert dark_gray.sum() == 0, f"text noise leaked: {dark_gray.sum()}"


def _badge_path(temp_dir, name="icon.png"):
    src = os.path.join(temp_dir, name)
    _make_badge().save(src)
    return src


def test_auto_mode():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = _badge_path(temp_dir)
        _run(src)
        _assert_glyph_only(os.path.join(temp_dir, "icon.clean.png"))


def test_auto_mode_multi_image():
    with tempfile.TemporaryDirectory() as temp_dir:
        src1 = _badge_path(temp_dir, "a.png")
        src2 = _badge_path(temp_dir, "b.png")
        _run(src1, src2)
        _assert_glyph_only(os.path.join(temp_dir, "a.clean.png"))
        _assert_glyph_only(os.path.join(temp_dir, "b.clean.png"))


def test_boxes_mode():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = _badge_path(temp_dir)
        _run(src, "--boxes", "80,80,120,120")
        _assert_glyph_only(os.path.join(temp_dir, "icon.clean.png"))


def test_disc_radius_override():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = _badge_path(temp_dir)
        _run(src, "--disc-radius", "60")
        _assert_glyph_only(os.path.join(temp_dir, "icon.clean.png"))


def test_manual_region_with_exclude():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = _badge_path(temp_dir)
        out = os.path.join(temp_dir, "manual.png")
        result = _run(src, "--region", "40,40,160,160", "--exclude-color", "#B4D3F0",
                      "--exclude-tol", "35", "-o", out)
        # Manual mode keeps every large component; the glyph must be present.
        a = np.asarray(Image.open(out).convert("RGBA"))
        fg = a[:, :, 3] > 128
        rgb = a[:, :, :3][fg].astype(int)
        deep_blue = (rgb[:, 2] > rgb[:, 0] + 40) & (rgb.max(1) - rgb.min(1) > 60)
        assert deep_blue.sum() > 200, result.stderr
        assert "bbox" in result.stdout


def main():
    test_auto_mode()
    test_auto_mode_multi_image()
    test_boxes_mode()
    test_disc_radius_override()
    test_manual_region_with_exclude()
    _run("--help")
    print("EXTRACT_FG TEST PASS")


if __name__ == "__main__":
    main()
