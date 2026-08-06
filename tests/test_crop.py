#!/usr/bin/env python3
"""Focused tests for the crop CLI (pixel box -> image file)."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_crop():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "crop")
    spec = importlib.util.spec_from_loader(
        "crop_cli", importlib.machinery.SourceFileLoader("crop_cli", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_region_parsing():
    mod = _load_crop()
    assert mod.parse_region("100,200,300,400") == (100, 200, 300, 400)
    for bad in ("1,2,3", "1,2,3,x", "1,2"):
        try:
            mod.parse_region(bad)
        except ValueError:
            continue
        raise AssertionError(f"region {bad!r} must be rejected")


def test_clamp_box():
    mod = _load_crop()
    assert mod.clamp_box((10, 20, 30, 40), 100, 100) == (10, 20, 30, 40)
    # Reversed corners are normalized.
    assert mod.clamp_box((30, 40, 10, 20), 100, 100) == (10, 20, 30, 40)
    # Out-of-bounds coordinates clamp to the image edges.
    assert mod.clamp_box((-20, 5, 300, 95), 200, 100) == (0, 5, 200, 95)


def _make_source(temp_dir, size=(200, 100), red_box=(40, 20, 160, 80)):
    image_path = os.path.join(temp_dir, "shot.png")
    image = Image.new("RGB", size, "white")
    for x in range(red_box[0], red_box[2]):
        for y in range(red_box[1], red_box[3]):
            image.putpixel((x, y), (255, 0, 0))
    image.save(image_path)
    return image_path


def test_cli_crop_default_output():
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "crop")
    with tempfile.TemporaryDirectory() as temp_dir:
        source = _make_source(temp_dir)
        result = subprocess.run([sys.executable, cli, source, "--region", "50,30,150,70"],
                                text=True, capture_output=True, check=True)
        output = os.path.join(temp_dir, "shot.crop.png")
        assert os.path.isfile(output), result.stderr
        assert f"wrote {output}" in result.stdout
        with Image.open(output) as crop:
            assert crop.size == (100, 40)
            assert crop.getpixel((5, 5)) == (255, 0, 0)


def test_cli_crop_custom_output_and_clamping():
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "crop")
    with tempfile.TemporaryDirectory() as temp_dir:
        source = _make_source(temp_dir)
        output = os.path.join(temp_dir, "custom.png")
        result = subprocess.run([sys.executable, cli, source, "--region=-20,5,300,95", "-o", output],
                                text=True, capture_output=True, check=True)
        assert "clamped" in result.stderr
        with Image.open(output) as crop:
            assert crop.size == (200, 90)


def test_cli_crop_errors():
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "crop")
    with tempfile.TemporaryDirectory() as temp_dir:
        source = _make_source(temp_dir)
        empty = subprocess.run([sys.executable, cli, source, "--region", "500,500,600,600"],
                               text=True, capture_output=True)
        assert empty.returncode != 0 and "empty" in empty.stderr

        missing = subprocess.run([sys.executable, cli, os.path.join(temp_dir, "nope.png"),
                                  "--region", "0,0,10,10"], text=True, capture_output=True)
        assert missing.returncode != 0 and "not found" in missing.stderr


def test_cli_crop_scale():
    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "crop")
    with tempfile.TemporaryDirectory() as temp_dir:
        source = _make_source(temp_dir)
        result = subprocess.run([sys.executable, cli, source, "--region", "50,30,150,70",
                                 "--scale", "4"],
                                text=True, capture_output=True, check=True)
        # Default output name carries the scale factor when scale > 1.
        output = os.path.join(temp_dir, "shot.crop@4x.png")
        assert os.path.isfile(output), result.stderr
        assert f"wrote {output} (400x160)" in result.stdout
        with Image.open(output) as crop:
            assert crop.size == (400, 160)
            # A pixel inside the red block stays red after upscaling.
            assert crop.getpixel((20, 20)) == (255, 0, 0)
        # Explicit -o wins over the scaled default name.
        custom = os.path.join(temp_dir, "scaled.png")
        subprocess.run([sys.executable, cli, source, "--region", "50,30,150,70",
                        "--scale", "2", "-o", custom],
                       text=True, capture_output=True, check=True)
        with Image.open(custom) as crop:
            assert crop.size == (200, 80)
        # Reject bad scale values.
        bad = subprocess.run([sys.executable, cli, source, "--region", "50,30,150,70",
                              "--scale", "0"], text=True, capture_output=True)
        assert bad.returncode != 0 and "--scale" in bad.stderr


def main():
    test_region_parsing()
    test_clamp_box()
    test_cli_crop_default_output()
    test_cli_crop_custom_output_and_clamping()
    test_cli_crop_errors()
    test_cli_crop_scale()
    subprocess.run([sys.executable,
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "crop"),
                    "--help"], check=True, stdout=subprocess.DEVNULL)
    print("CROP TEST PASS")


if __name__ == "__main__":
    main()
