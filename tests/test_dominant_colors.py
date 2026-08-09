#!/usr/bin/env python3
"""Unit + CLI test: dominant_colors clustering, candidate picking, and output."""

import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "skills", "vision-tools", "scripts", "dominant_colors.py")


def load_module():
    spec = importlib.util.spec_from_loader(
        "dominant_colors_mod",
        importlib.machinery.SourceFileLoader("dominant_colors_mod", SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return load_module()


@pytest.fixture
def temp_dir(tmp_path):
    return str(tmp_path)


def test_extract_top_colours(mod):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (200, 100))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 99, 99), fill=(245, 245, 245))    # #F5F5F5
    draw.rectangle((100, 0, 199, 99), fill=(249, 115, 22))  # #F97316 orange
    clusters = mod.extract(image, (0, 0, 200, 100), top=2, quantize_k=16,
                           max_pixels=96, merge_tol=8)
    assert clusters[0].count > 0
    shares = {mod.hex_of(c.rgb): c.count for c in clusters}
    assert any(key.startswith("#F") for key in shares), shares
    assert any(key.startswith("#F9") for key in shares), shares
    total = sum(c.count for c in clusters)
    assert abs(sum(c.count for c in clusters[:2]) / total - 1.0) < 0.05
    print("PASS: extract returns the dominant colours with proportions")


def test_extract_merges_near_duplicates(mod):
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (200, 100), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 99, 99), fill=(243, 243, 243))  # #F3F3F3, delta 2
    clusters = mod.extract(image, (0, 0, 200, 100), top=3, quantize_k=16,
                           max_pixels=96, merge_tol=8)
    top_share = clusters[0].count / sum(c.count for c in clusters)
    assert top_share > 0.9, [mod.hex_of(c.rgb) for c in clusters]
    print("PASS: near-duplicate colours merge into one cluster")


def test_pick_wins_the_exact_candidate(mod):
    from PIL import Image
    image = Image.new("RGB", (60, 30), (245, 245, 245))  # #F5F5F5
    candidates = ["#F9FAFA", "#F5F5F5", "#F3F3F3", "#EDEDED"]
    rows, winner, _closest = mod.pick(image, (0, 0, 60, 30), candidates, tol=16)
    assert winner["text"] == "#F5F5F5", winner
    assert winner["share"] == 100.0, winner
    print("PASS: the exact candidate wins over near neighbours inside the tolerance")


def test_pick_disambiguates_with_weighted_support(mod):
    from PIL import Image
    image = Image.new("RGB", (60, 30), (237, 237, 237))  # #EDEDED
    candidates = ["#F9FAFA", "#F5F5F5", "#EDEDED"]
    rows, winner, _closest = mod.pick(image, (0, 0, 60, 30), candidates, tol=16)
    assert winner["text"] == "#EDEDED", winner
    print("PASS: weighted support prefers the closer candidate")


def test_pick_reports_no_match(mod):
    from PIL import Image
    image = Image.new("RGB", (40, 40), (0, 0, 255))  # blue, far from grays
    candidates = ["#F9FAFA", "#F5F5F5"]
    rows, winner, closest = mod.pick(image, (0, 0, 40, 40), candidates, tol=16)
    assert winner["hard"] == 0
    assert closest["text"] == "#F5F5F5"  # blue is nearer #F5F5F5 than #F9FAFA
    print("PASS: no candidate within tolerance is reported with the closest one")


def test_region_clamps_and_parses(mod):
    from PIL import Image
    image = Image.new("RGB", (100, 80))
    box = mod.parse_region("-10,-10,120,90", 100, 80)
    assert box == (0, 0, 100, 80), box
    try:
        mod.parse_region("0,0", 100, 80)
        raise AssertionError("expected ValueError for a malformed region")
    except ValueError:
        pass
    try:
        mod.parse_region("50,50,50,60", 100, 80)
        raise AssertionError("expected ValueError for an empty region")
    except ValueError:
        pass
    print("PASS: regions clamp to the image and reject malformed/empty boxes")


def test_cli(mod, temp_dir):
    from PIL import Image, ImageDraw
    image = os.path.join(temp_dir, "region.png")
    source = Image.new("RGB", (120, 80), (245, 245, 245))
    ImageDraw.Draw(source).rectangle((60, 0, 119, 79), fill=(249, 115, 22))
    source.save(image)

    picked = subprocess.run(
        [sys.executable, SCRIPT, image, "--region", "0,0,60,80",
         "--candidates", "#F9FAFA,#F5F5F5,#EDEDED"],
        text=True, capture_output=True, check=True)
    assert "winner: #F5F5F5" in picked.stdout, picked.stdout

    extracted = subprocess.run(
        [sys.executable, SCRIPT, image, "--region", "60,0,120,80", "--top", "2"],
        text=True, capture_output=True, check=True)
    assert "#F97316" in extracted.stdout or "#F9" in extracted.stdout, extracted.stdout

    missing = subprocess.run(
        [sys.executable, SCRIPT, os.path.join(temp_dir, "nope.png")],
        text=True, capture_output=True)
    assert missing.returncode != 0 and "image not found" in missing.stderr
    print("PASS: CLI extract/pick output and missing-file handling")


def main():
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print("SKIP: Pillow not installed; dominant_colors is an optional feature")
        return
    mod = load_module()
    test_extract_top_colours(mod)
    test_extract_merges_near_duplicates(mod)
    test_pick_wins_the_exact_candidate(mod)
    test_pick_disambiguates_with_weighted_support(mod)
    test_pick_reports_no_match(mod)
    test_region_clamps_and_parses(mod)
    with tempfile.TemporaryDirectory() as temp_dir:
        test_cli(mod, temp_dir)
    subprocess.run([sys.executable, SCRIPT, "--help"], check=True, stdout=subprocess.DEVNULL)
    print("DOMINANT_COLORS TEST PASS")


if __name__ == "__main__":
    main()
