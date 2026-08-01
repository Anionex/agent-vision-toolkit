from __future__ import annotations

import argparse
import json
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


def build_prompt(target: str) -> str:
    return (
        "Locate every visible object or region matching this target:\n"
        f"{target}\n\n"
        'Return only a JSON array. Each item must contain "box_2d" as '
        '[y0, x0, y1, x1] on a 0-1000 grid and "label" as a short description. '
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
        fallback = _fallback_items(cleaned)
        if fallback:
            return fallback
        raise GroundError("视觉 API 没有返回可解析的边界框 JSON")
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("boxes", "bounding_boxes", "bboxes", "objects", "items", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise GroundError("视觉 API 返回的边界框 JSON 结构不兼容")


def _normalize_box(item: dict[str, Any], width: int, height: int) -> tuple[int, int, int, int] | None:
    raw = item.get("box_2d")
    if not isinstance(raw, list):
        for key in ("bbox_2d", "box2d", "bbox", "box"):
            if isinstance(item.get(key), list):
                raw = item[key]
                break
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        y0, x0, y1, x1 = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
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


def parse_matches(text: str, width: int, height: int, target: str) -> list[Match]:
    matches = []
    for item in _items(text):
        if not isinstance(item, dict):
            continue
        box = _normalize_box(item, width, height)
        if box is None:
            continue
        label = str(item.get("label") or item.get("caption") or item.get("description") or target).strip()
        matches.append(Match(label or target, box))
    return matches


def locate(image_path: Path, target: str) -> list[Match]:
    if Image is None:
        raise GroundError("ground 需要 Pillow；请先安装可选依赖 pillow")
    load_default_env()
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except (OSError, ValueError) as exc:
        raise GroundError(f"无法读取图片: {image_path}") from exc
    response = describe_image(image_path_to_data_url(image_path), build_prompt(target), max_tokens=2048)
    return parse_matches(response, width, height, target)


def _position(box: tuple[int, int, int, int], width: int, height: int) -> str:
    x1, y1, x2, y2 = box
    x = (x1 + x2) / 2
    y = (y1 + y2) / 2
    horizontal = "左" if x < width / 3 else ("右" if x > width * 2 / 3 else "中")
    vertical = "上" if y < height / 3 else ("下" if y > height * 2 / 3 else "中")
    return {
        ("左", "上"): "左上", ("中", "上"): "上", ("右", "上"): "右上",
        ("左", "中"): "左", ("中", "中"): "中央", ("右", "中"): "右",
        ("左", "下"): "左下", ("中", "下"): "下", ("右", "下"): "右下",
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
        description="用自然语言定位图片中的目标并输出像素坐标",
    )
    parser.add_argument("image", type=Path, help="图片路径")
    parser.add_argument("target", help="要定位的对象或区域")
    args = parser.parse_args()
    try:
        matches = locate(args.image.expanduser(), args.target)
        if Image is None:
            raise GroundError("ground 需要 Pillow；请先安装可选依赖 pillow")
        with Image.open(args.image.expanduser()) as image:
            width, height = image.size
    except (GroundError, VisionError) as exc:
        parser.exit(1, f"ground: {exc}\n")
    for line in format_matches(matches, width, height):
        print(line)


if __name__ == "__main__":
    main()
