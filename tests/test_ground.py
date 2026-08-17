#!/usr/bin/env python3
"""Focused tests for the optional ground CLI."""

import subprocess
import sys
import tempfile
import os
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


def test_qwen_xyxy_box_parsing_on_non_square_image():
    text = '[{"box_2d": [333, 34, 827, 82], "label": "title"}]'
    assert ground.parse_matches(text, 1200, 675, "target", "xyxy") == [
        ground.Match("title", (400, 23, 992, 55))
    ]


def test_coordinate_order_uses_model_family_and_override():
    original_model = os.environ.get("VISION_MODEL")
    original_order = os.environ.get("VISION_BOX_ORDER")
    try:
        os.environ["VISION_MODEL"] = "qwen/qwen3.6-27b"
        os.environ.pop("VISION_BOX_ORDER", None)
        assert ground.coordinate_order() == "xyxy"
        os.environ["VISION_MODEL"] = "gemini-2.5-flash"
        assert ground.coordinate_order() == "yxyx"
        os.environ["VISION_BOX_ORDER"] = "xyxy"
        assert ground.coordinate_order() == "xyxy"
    finally:
        if original_model is None:
            os.environ.pop("VISION_MODEL", None)
        else:
            os.environ["VISION_MODEL"] = original_model
        if original_order is None:
            os.environ.pop("VISION_BOX_ORDER", None)
        else:
            os.environ["VISION_BOX_ORDER"] = original_order


def test_truncated_json_does_not_return_partial_matches():
    truncated = '```json\n[{"box_2d": [0, 0, 100, 100], "label": "first"}, {"box_2d": [100'
    try:
        ground.parse_matches(truncated, 1200, 675, "target")
    except ground.GroundError as exc:
        assert "truncated or incomplete" in str(exc)
    else:
        raise AssertionError("truncated bounding-box JSON must fail closed")


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
    test_qwen_xyxy_box_parsing_on_non_square_image()
    test_coordinate_order_uses_model_family_and_override()
    test_truncated_json_does_not_return_partial_matches()
    test_shared_vision_request()
    test_output_format()
    subprocess.run([sys.executable, "bin/ground", "--help"], check=True, stdout=subprocess.DEVNULL)
    print("GROUND TEST PASS")


if __name__ == "__main__":
    main()
