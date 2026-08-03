#!/usr/bin/env python3
"""pixel_diff: compare a rebuilt image against the original and rank the worst regions.

Verification is the step agents skip or fake, because comparing two
descriptions feels like comparing two images. It is not. This runs the real
comparison and answers the only question that matters next: which region is
most wrong, so you know where to look and what to fix first.

Boxes are printed in the same `x1: .., y1: ..` form as ground/detect, so a
bad region can be pasted straight into `glance --region` or `detect --region`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageStat
except ImportError:
    Image = None


def load(path: Path, size: tuple[int, int] | None = None) -> "Image.Image":
    # Traced SVGs and screenshots of transparent UI render with an alpha
    # channel; unflattened transparency reads as black and shows up as a huge
    # phantom diff. Compositing on white is what a viewer would show.
    image = Image.open(path)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        canvas = Image.new("RGB", image.size, "white")
        canvas.paste(image, mask=image.split()[-1])
        image = canvas
    else:
        image = image.convert("RGB")
    return image.resize(size, Image.LANCZOS) if size and image.size != size else image


def cell_scores(diff: "Image.Image", grid: int) -> list[tuple[float, tuple[int, int, int, int]]]:
    width, height = diff.size
    grey = diff.convert("L")
    scores = []
    for row in range(grid):
        for column in range(grid):
            box = (round(column * width / grid), round(row * height / grid),
                   round((column + 1) * width / grid), round((row + 1) * height / grid))
            if box[2] > box[0] and box[3] > box[1]:
                mean = ImageStat.Stat(grey.crop(box)).mean[0]
                scores.append((mean / 255 * 100, box))
    return sorted(scores, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pixel_diff",
        description="Pixel-diff a rebuilt image against the original and rank the worst regions",
    )
    parser.add_argument("original", type=Path, help="the reference image")
    parser.add_argument("rebuilt", type=Path, help="your rendered reproduction")
    parser.add_argument("--grid", type=int, default=6, help="split into GRID x GRID cells (default: 6)")
    parser.add_argument("--top", type=int, default=5, help="how many worst regions to print (default: 5)")
    parser.add_argument("-o", "--output", type=Path, help="write a diff heatmap image here")
    args = parser.parse_args()
    if Image is None:
        parser.exit(1, "pixel_diff: requires Pillow; install the optional dependency pillow first\n")
    for path in (args.original, args.rebuilt):
        if not path.expanduser().is_file():
            parser.exit(1, f"pixel_diff: image not found: {path}\n")
    original = load(args.original.expanduser())
    with Image.open(args.rebuilt.expanduser()) as probe:
        raw_size = probe.size
    rebuilt = load(args.rebuilt.expanduser(), size=original.size)
    if raw_size != original.size:
        # Worth saying out loud: a size mismatch is itself a finding, and every
        # box printed below is in the original's coordinates, not the rebuild's.
        print(f"note: rebuilt was {raw_size[0]}x{raw_size[1]}, scaled to {original.size[0]}x{original.size[1]}")
    diff = ImageChops.difference(original, rebuilt)
    overall = ImageStat.Stat(diff.convert("L")).mean[0] / 255 * 100
    print(f"overall difference: {overall:.2f}%")
    if args.output:
        diff.save(args.output.expanduser())
        print(f"heatmap: {args.output}")
    for index, (score, box) in enumerate(cell_scores(diff, args.grid)[:args.top], 1):
        print(f"{index}. {score:.2f}% x1: {box[0]}, y1: {box[1]}, x2: {box[2]}, y2: {box[3]}")


if __name__ == "__main__":
    main()
