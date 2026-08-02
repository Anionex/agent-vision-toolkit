#!/usr/bin/env python3
"""Unit test: glance --region crops locally and only the crop is uploaded."""

import base64
import importlib.machinery
import importlib.util
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from PIL import Image
except ImportError:
    print("SKIP: Pillow not installed; --region is an optional feature")
    sys.exit(0)


def _load_glance():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "glance")
    spec = importlib.util.spec_from_loader(
        "glance_cli", importlib.machinery.SourceFileLoader("glance_cli", path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    mod = _load_glance()
    with tempfile.TemporaryDirectory() as raw:
        path = os.path.join(raw, "fixture.png")
        image = Image.new("RGB", (40, 20), (255, 0, 0))
        for x in range(20, 40):
            for y in range(20):
                image.putpixel((x, y), (0, 255, 0))
        image.save(path)

        url = mod.region_data_url(path, "20,0,40,20")
        assert url.startswith("data:image/png;base64,")
        crop = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
        assert crop.size == (20, 20), crop.size
        assert crop.getpixel((10, 10)) == (0, 255, 0), "crop must contain only the green half"

        swapped = mod.region_data_url(path, "40,20,20,0")
        assert swapped == url, "swapped corners must normalize to the same box"

        for bad in ("1,2,3", "a,b,c,d", "50,0,60,20"):
            try:
                mod.region_data_url(path, bad)
            except mod.VisionError:
                pass
            else:
                raise AssertionError(f"region {bad!r} must be rejected")

    print("GLANCE REGION TEST PASS")


if __name__ == "__main__":
    main()
