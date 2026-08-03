#!/usr/bin/env python3
"""Focused tests for the optional detect CLI and ground --region mapping."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import detect
import ground


def test_target_construction():
    assert "every distinct UI element" in detect.build_target(None)
    assert "exact visible text" in detect.build_target(None)
    assert "every distinct buttons" in detect.build_target("buttons")


def test_region_boxes_map_back_to_original_coordinates():
    original = ground.describe_image
    seen = {}

    def fake_describe(image_url, prompt, max_tokens=None):
        seen.update(image_url=image_url, prompt=prompt)
        return '[{"box_2d": [0, 0, 1000, 1000], "label": "icon"}]'

    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "image.png"
        Image.new("RGB", (200, 100)).save(image_path)
        ground.describe_image = fake_describe
        try:
            result = ground.locate(image_path, "icon", region="50,20,150,80")
        finally:
            ground.describe_image = original

    assert result == [ground.Match("icon", (50, 20, 150, 80))], result
    assert seen["image_url"].startswith("data:image/png;base64,")


def test_region_validation():
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "image.png"
        Image.new("RGB", (200, 100)).save(image_path)
        for bad in ("1,2,3", "500,500,600,600"):
            try:
                ground.locate(image_path, "x", region=bad)
            except ground.GroundError:
                continue
            raise AssertionError(f"region {bad!r} must be rejected")


def test_inventory_output_is_always_numbered():
    matches = [ground.Match("button: Docs", (0, 0, 100, 100))]
    lines = detect.format_inventory(matches, 1200, 900)
    assert lines == ["1. top-left button: Docs x1: 0, y1: 0, x2: 100, y2: 100"]
    assert detect.format_inventory([], 1200, 900) == ["no elements detected"]


def main():
    test_target_construction()
    test_region_boxes_map_back_to_original_coordinates()
    test_region_validation()
    test_inventory_output_is_always_numbered()
    subprocess.run([sys.executable, "bin/detect", "--help"], check=True, stdout=subprocess.DEVNULL)
    print("DETECT TEST PASS")


if __name__ == "__main__":
    main()
