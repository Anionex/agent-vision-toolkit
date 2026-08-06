#!/usr/bin/env python3
"""Focused tests for extract_icon.py (auto icon foreground extraction)."""

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
    # dark text-like noise far from the disc (must NOT be extracted)
    for y in range(h - 20, h - 8):
        for x in range(w - 30, w - 15):
            px[x, y] = (85, 85, 85)
    return img


def _run_extract(image_path, *extra):
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir,
                       "skills", "vision-tools", "scripts", "extract_icon.py")
    return subprocess.run([sys.executable, cli, image_path, *extra],
                          text=True, capture_output=True, check=True)


def _assert_clean_output(image_path):
    clean = os.path.join(os.path.dirname(image_path),
                         os.path.splitext(os.path.basename(image_path))[0] + ".clean.png")
    assert os.path.isfile(clean)
    a = np.asarray(Image.open(clean).convert("RGBA"))
    fg = a[:, :, 3] > 128
    assert fg.sum() > 200, f"too little foreground: {fg.sum()}"
    rgb = a[:, :, :3][fg].astype(int)
    # glyph color dominates (deep blue, high saturation)
    sat = rgb.max(1) - rgb.min(1)
    deep_blue = (rgb[:, 2] > rgb[:, 0] + 40) & (sat > 60)
    assert deep_blue.mean() > 0.85, f"glyph share too low: {deep_blue.mean():.2f}"
    # light-blue disc and dark text noise must be gone
    disc_like = (np.abs(rgb[:, 0] - 180) < 30) & (np.abs(rgb[:, 1] - 211) < 30)
    assert disc_like.mean() < 0.05, f"disc residue too high: {disc_like.mean():.2f}"
    dark_gray = (np.abs(rgb[:, 0] - 85) < 25) & (np.abs(rgb[:, 1] - 85) < 25)
    assert dark_gray.sum() == 0, f"text noise leaked: {dark_gray.sum()}"
    return clean


def test_auto_mode():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = os.path.join(temp_dir, "icon.png")
        _make_badge().save(src)
        _run_extract(src)
        _assert_clean_output(src)


def test_boxes_mode():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = os.path.join(temp_dir, "icon.png")
        _make_badge().save(src)
        _run_extract(src, "--boxes", "80,80,120,120")
        _assert_clean_output(src)


def test_disc_radius_override():
    with tempfile.TemporaryDirectory() as temp_dir:
        src = os.path.join(temp_dir, "icon.png")
        _make_badge().save(src)
        _run_extract(src, "--disc-radius", "60")
        _assert_clean_output(src)


def main():
    test_auto_mode()
    test_boxes_mode()
    test_disc_radius_override()
    print("EXTRACT_ICON TEST PASS")


if __name__ == "__main__":
    main()
