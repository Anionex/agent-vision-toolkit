from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:
    Image = None

from vision_client import VisionError, describe_image, image_path_to_data_url, load_default_env


@dataclass(frozen=True)
class Match:
    label: str
    bbox: tuple[int, int, int, int]


class GroundError(Exception):
    pass


def coordinate_order() -> str:
    configured = os.environ.get("VISION_BOX_ORDER", "").strip().lower()
    if configured:
        if configured not in {"xyxy", "yxyx"}:
            raise GroundError("VISION_BOX_ORDER must be either xyxy or yxyx")
        return configured
    model = os.environ.get("VISION_MODEL", "").lower()
    return "xyxy" if "qwen" in model else "yxyx"


def build_prompt(target: str, box_order: str = "yxyx") -> str:
    coordinates = "[x0, y0, x1, y1]" if box_order == "xyxy" else "[y0, x0, y1, x1]"
    return (
        "Locate every visible object or region matching this target:\n"
        f"{target}\n\n"
        'Return only a JSON array. Each item must contain "box_2d" as '
        f'{coordinates} on a 0-1000 grid and "label" as a short description. '
        "Use tight boxes in the original image. Return [] when nothing matches."
    )


def _json_text(text: str) -> str:
    cleaned = str(text or "").strip()
    fenced = re.findall(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    return (fenced[-1] if fenced else cleaned).strip()


def _fallback_items(text: str) -> list[dict[str, Any]]:
    items = []
    object_pattern = re.compile(r"\{[^{}]*['\"](?:box_2d|bbox_2d|box2d|bbox|box)['\"]\s*:\s*\[[^\]]+\][^{}]*\}", re.DOTALL)
    box_pattern = re.compile(r"['\"](?:box_2d|bbox_2d|box2d|bbox|box)['\"]\s*:\s*\[([^\]]+)\]", re.DOTALL)
    label_pattern = re.compile(r"['\"](?:label|caption|description)['\"]\s*:\s*['\"]([^'\"]+)['\"]", re.DOTALL)
    for match in object_pattern.finditer(text):
        block = match.group(0)
        box_match = box_pattern.search(block)
        if not box_match:
            continue
        numbers = re.findall(r"-?\d+(?:\.\d+)?", box_match.group(1))
        if len(numbers) < 4:
            continue
        item: dict[str, Any] = {"box_2d": [float(value) for value in numbers[:4]]}
        label_match = label_pattern.search(block)
        if label_match:
            item["label"] = label_match.group(1).strip()
        items.append(item)
    return items


def _items(text: str) -> list[Any]:
    cleaned = _json_text(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        if cleaned.count("```") % 2 or _has_unclosed_json(cleaned):
            raise GroundError("Vision API bounding-box JSON was truncated or incomplete") from None
        fallback = _fallback_items(cleaned)
        if fallback:
            return fallback
        raise GroundError("Vision API did not return parseable bounding-box JSON")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("boxes", "bounding_boxes", "bboxes", "objects", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise GroundError("Vision API returned an incompatible bounding-box JSON structure")


def _has_unclosed_json(text: str) -> bool:
    start_positions = [position for position in (text.find("["), text.find("{")) if position >= 0]
    if not start_positions:
        return False
    stack = []
    in_string = False
    escaped = False
    pairs = {"]": "[", "}": "{"}
    for character in text[min(start_positions):]:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            stack.append(character)
        elif character in "]}":
            if not stack or stack[-1] != pairs[character]:
                return False
            stack.pop()
    return bool(stack)


def _normalize_box(
    item: dict[str, Any], width: int, height: int, box_order: str = "yxyx",
) -> tuple[int, int, int, int] | None:
    raw = item.get("box_2d")
    if not isinstance(raw, list):
        for key in ("bbox_2d", "box2d", "bbox", "box"):
            if isinstance(item.get(key), list):
                raw = item[key]
                break
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        values = tuple(float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if box_order == "xyxy":
        x0, y0, x1, y1 = values
    else:
        y0, x0, y1, x1 = values
    if x0 > x1:
        x0, x1 = x1, x0
    if y0 > y1:
        y0, y1 = y1, y0
    box = (
        max(0, min(width, round(x0 / 1000 * width))),
        max(0, min(height, round(y0 / 1000 * height))),
        max(0, min(width, round(x1 / 1000 * width))),
        max(0, min(height, round(y1 / 1000 * height))),
    )
    return box if box[2] > box[0] and box[3] > box[1] else None


def parse_matches(
    text: str, width: int, height: int, target: str, box_order: str = "yxyx",
) -> list[Match]:
    matches = []
    for item in _items(text):
        if not isinstance(item, dict):
            continue
        box = _normalize_box(item, width, height, box_order)
        if box is None:
            continue
        label = str(item.get("label") or item.get("caption") or item.get("description") or target).strip()
        matches.append(Match(label or target, box))
    return matches


def _parse_region(region: str, width: int, height: int) -> tuple[int, int, int, int]:
    try:
        x1, y1, x2, y2 = (int(value) for value in region.split(","))
    except ValueError:
        raise GroundError("--region expects four integers: X1,Y1,X2,Y2 (pixels)") from None
    box = (max(0, min(x1, x2)), max(0, min(y1, y2)),
           min(width, max(x1, x2)), min(height, max(y1, y2)))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise GroundError(f"--region {region} is empty after clamping to {width}x{height}")
    return box


def locate(image_path: Path, target: str, region: str | None = None) -> list[Match]:
    if Image is None:
        raise GroundError("ground requires Pillow; install the optional dependency pillow first")
    load_default_env()
    box = None
    try:
        with Image.open(image_path) as image:
            width, height = image.size
            if region:
                box = _parse_region(region, width, height)
                buffer = io.BytesIO()
                image.crop(box).save(buffer, format="PNG")
                url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    except (OSError, ValueError) as exc:
        raise GroundError(f"Cannot read image: {image_path}") from exc
    if box is None:
        url = image_path_to_data_url(image_path)
        width_used, height_used = width, height
    else:
        width_used, height_used = box[2] - box[0], box[3] - box[1]
    # 8192 leaves room for exhaustive targets ("every UI element"): a dense
    # screen can emit dozens of boxes and 2048 truncated the JSON mid-array.
    box_order = coordinate_order()
    response = describe_image(url, build_prompt(target, box_order), max_tokens=8192)
    matches = parse_matches(response, width_used, height_used, target, box_order)
    if box is None:
        return matches
    # Matches were parsed in crop coordinates; report them in the original image.
    return [Match(m.label, (m.bbox[0] + box[0], m.bbox[1] + box[1],
                            m.bbox[2] + box[0], m.bbox[3] + box[1])) for m in matches]


def _position(box: tuple[int, int, int, int], width: int, height: int) -> str:
    x1, y1, x2, y2 = box
    x = (x1 + x2) / 2
    y = (y1 + y2) / 2
    horizontal = "left" if x < width / 3 else ("right" if x > width * 2 / 3 else "center")
    vertical = "top" if y < height / 3 else ("bottom" if y > height * 2 / 3 else "center")
    return {
        ("left", "top"): "top-left", ("center", "top"): "top", ("right", "top"): "top-right",
        ("left", "center"): "left", ("center", "center"): "center", ("right", "center"): "right",
        ("left", "bottom"): "bottom-left", ("center", "bottom"): "bottom", ("right", "bottom"): "bottom-right",
    }[(horizontal, vertical)]


def format_matches(matches: list[Match], width: int, height: int) -> list[str]:
    if len(matches) == 1:
        x1, y1, x2, y2 = matches[0].bbox
        return [f"x1: {x1}, y1: {y1}, x2: {x2}, y2: {y2}"]
    lines = []
    for index, match in enumerate(matches, 1):
        x1, y1, x2, y2 = match.bbox
        position = _position(match.bbox, width, height)
        lines.append(f"{index}. {position} {match.label} x1: {x1}, y1: {y1}, x2: {x2}, y2: {y2}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ground",
        description="Locate targets in an image with natural language and output pixel coordinates",
    )
    parser.add_argument("image", type=Path, help="path to the image")
    parser.add_argument("target", help="target object or region to locate")
    parser.add_argument("--region", metavar="X1,Y1,X2,Y2",
                        help="search only this pixel box; output stays in original-image coordinates")
    args = parser.parse_args()
    try:
        matches = locate(args.image.expanduser(), args.target, region=args.region)
        if Image is None:
            raise GroundError("ground requires Pillow; install the optional dependency pillow first")
        with Image.open(args.image.expanduser()) as image:
            width, height = image.size
    except (GroundError, VisionError) as exc:
        parser.exit(1, f"ground: {exc}\n")
    for line in format_matches(matches, width, height):
        print(line)


if __name__ == "__main__":
    main()
