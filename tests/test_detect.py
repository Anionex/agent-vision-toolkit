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
    complete = "every distinct UI element — include the exact visible text in each label"
    assert detect.build_target(complete) == complete


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


def run_detect_cli(image_path, response, *args):
    # Exercise the real launcher, parser, grounding and process exit status,
    # replacing only the model response and user-specific configuration.
    code = """
import runpy
import sys
import ground

response = sys.argv.pop(1)
ground.describe_image = lambda *args, **kwargs: response
ground.load_default_env = lambda: None
ground.coordinate_order = lambda: "yxyx"
sys.argv[0] = "bin/detect"
runpy.run_path("bin/detect", run_name="__main__")
"""
    return subprocess.run(
        [sys.executable, "-c", code, response, str(image_path), *args],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, timeout=10,
    )


def test_cli_empty_exit_is_opt_in():
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "image.png"
        Image.new("RGB", (200, 100)).save(image_path)
        for args in ((), ("text", "--region", "50,20,150,80")):
            result = run_detect_cli(image_path, "[]", *args)
            assert result.returncode == 0, result.stderr
            assert result.stdout == "no elements detected\n", result.stdout
            assert result.stderr == "", result.stderr

            result = run_detect_cli(image_path, "[]", *args, "--fail-on-empty")
            assert result.returncode == 1, result.stderr
            assert result.stdout == "", result.stdout
            assert result.stderr == "detect: no elements detected\n", result.stderr


def test_cli_nonempty_output_is_unchanged():
    response = '[{"box_2d": [0, 0, 1000, 1000], "label": "caption"}]'
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "image.png"
        Image.new("RGB", (200, 100)).save(image_path)
        for args, expected in (
            ((), "1. center caption x1: 0, y1: 0, x2: 200, y2: 100\n"),
            (("text", "--region", "50,20,150,80"),
             "1. center caption x1: 50, y1: 20, x2: 150, y2: 80\n"),
        ):
            for flag in ((), ("--fail-on-empty",)):
                result = run_detect_cli(image_path, response, *args, *flag)
                assert result.returncode == 0, result.stderr
                assert result.stdout == expected, result.stdout
                assert result.stderr == "", result.stderr


def test_cli_model_errors_remain_errors():
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "image.png"
        Image.new("RGB", (200, 100)).save(image_path)
        for flag in ((), ("--fail-on-empty",)):
            result = run_detect_cli(image_path, "not JSON", *flag)
            assert result.returncode == 1, result.stderr
            assert result.stdout == "", result.stdout
            assert "did not return parseable bounding-box JSON" in result.stderr, result.stderr
            assert "no elements detected" not in result.stderr, result.stderr


def main():
    test_target_construction()
    test_region_boxes_map_back_to_original_coordinates()
    test_region_validation()
    test_inventory_output_is_always_numbered()
    test_cli_empty_exit_is_opt_in()
    test_cli_nonempty_output_is_unchanged()
    test_cli_model_errors_remain_errors()
    subprocess.run([sys.executable, "bin/detect", "--help"], check=True, stdout=subprocess.DEVNULL)
    print("DETECT TEST PASS")


if __name__ == "__main__":
    main()
