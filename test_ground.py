#!/usr/bin/env python3
"""Focused tests for the optional ground CLI."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

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
    assert seen["max_tokens"] == 2048


def main():
    test_box_parsing()
    test_shared_vision_request()
    subprocess.run([sys.executable, "bin/ground", "--help"], check=True, stdout=subprocess.DEVNULL)
    print("GROUND TEST PASS")


if __name__ == "__main__":
    main()
