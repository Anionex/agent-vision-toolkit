from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

from ground import GroundError, _position, locate
from vision_client import VisionError

DEFAULT_CATEGORY = ("UI element (buttons, links, inputs, icons, labels, "
                    "headings, images, badges)")


def build_target(category: str | None) -> str:
    return (f"every distinct {category or DEFAULT_CATEGORY} — "
            "include the exact visible text in each label")


def format_inventory(matches, width: int, height: int) -> list[str]:
    lines = []
    for index, match in enumerate(matches, 1):
        x1, y1, x2, y2 = match.bbox
        position = _position(match.bbox, width, height)
        lines.append(f"{index}. {position} {match.label} x1: {x1}, y1: {y1}, x2: {x2}, y2: {y2}")
    return lines or ["no elements detected"]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="detect",
        description="Inventory the elements in an image (or a region) with pixel bounding boxes",
    )
    parser.add_argument("image", type=Path, help="path to the image")
    parser.add_argument("category", nargs="?",
                        help='restrict to a category, e.g. "buttons" or "icons" (default: all UI elements)')
    parser.add_argument("--region", metavar="X1,Y1,X2,Y2",
                        help="inventory only this pixel box; output stays in original-image coordinates")
    args = parser.parse_args()
    try:
        matches = locate(args.image.expanduser(), build_target(args.category), region=args.region)
        if Image is None:
            raise GroundError("detect requires Pillow; install the optional dependency pillow first")
        with Image.open(args.image.expanduser()) as image:
            width, height = image.size
    except (GroundError, VisionError) as exc:
        parser.exit(1, f"detect: {exc}\n")
    for line in format_inventory(matches, width, height):
        print(line)


if __name__ == "__main__":
    main()
