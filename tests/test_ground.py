#!/usr/bin/env python3
"""Focused tests for the optional ground CLI."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ground


def test_box_parsing():
    text = '[{"box_2d": [100, 200, 500, 800], "label": "button"}]'
    assert ground.parse_matches(text, 200, 100, "target") == [
        ground.Match("button", (40, 10, 160, 50))
    ]

    malformed = "result: {'bbox': [0, 0, 1000, 1000], 'label': 'page'}"
    assert ground.parse_matches(malformed, 80, 60, "target") == [
        ground.Match("page", (0, 0, 80, 60))
    ]

    assert ground.parse_matches("[]", 80, 60, "target") == []


def test_shared_vision_request():
    original = ground.describe_image
    seen = {}

    def fake_describe(image_url, prompt, max_tokens=None):
        seen.update(image_url=image_url, prompt=prompt, max_tokens=max_tokens)
        return '[{"box_2d": [0, 0, 1000, 1000], "label": "whole image"}]'

    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "image.png"
        Image.new("RGB", (16, 12)).save(image_path)
        ground.describe_image = fake_describe
        try:
            result = ground.locate(image_path, "page")
        finally:
            ground.describe_image = original

    assert result == [ground.Match("whole image", (0, 0, 16, 12))]
    assert seen["image_url"].startswith("data:image/png;base64,")
    assert "page" in seen["prompt"]
    assert seen["max_tokens"] == 8192


def test_output_format():
    single = [ground.Match("button", (64, 756, 1120, 890))]
    assert ground.format_matches(single, 1200, 900) == [
        "x1: 64, y1: 756, x2: 1120, y2: 890"
    ]

    multiple = [
        ground.Match("first", (0, 0, 100, 100)),
        ground.Match("second", (900, 700, 1000, 800)),
    ]
    lines = ground.format_matches(multiple, 1200, 900)
    assert lines[0].startswith("1. top-left first ")
    assert lines[1].startswith("2. bottom-right second ")


def main():
    test_box_parsing()
    test_shared_vision_request()
    test_output_format()
    subprocess.run([sys.executable, "bin/ground", "--help"], check=True, stdout=subprocess.DEVNULL)
    print("GROUND TEST PASS")


if __name__ == "__main__":
    main()
