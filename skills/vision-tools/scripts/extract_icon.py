#!/usr/bin/env python3
"""extract_icon.py — 从放大的图标截图里提取干净前景（透明 PNG）。

只负责「圆底主色采样 → extract_fg 排除背景 → 连通分量挑选 → 导出」；
裁剪放大（crop --scale）由 crop CLI 完成。输入图已精确裁出图标主体，
中心/半径自动从前景推断，默认不用传任何定位参数：

  crop shot.png --region 40,445,110,505 --scale 4 -o d/icon1.png
  python3 extract_icon.py d/icon1.png d/icon2.png

可选增强：--boxes 传 ground 在放大图上的框（分号分隔，与图片一一对应），
用于圆心/半径校正与分量重叠筛选；--disc-radius 可显式覆盖圆底半径（放大图像素）。
搜索区域固定为整张放大图（crop 已精确裁出图标），不暴露 region 概念。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from extract_fg import connected_components


def _parse_boxes(text: str) -> list[list[int]]:
    return [[int(v) for v in part.split(",")] for part in text.split(";") if part.strip()]


def _pick_component(ink: set, shape: tuple[int, int], rgb: np.ndarray,
                    box: list[int] | None = None) -> set | None:
    comps = connected_components(ink, *shape)
    if not comps:
        return None
    if box is None:
        # auto：先按大小取前 3 大彩色分量（图形主体必然在前列），再在其中选饱和度
        # 最高的——避免小残片 sat 虚高抢位，也避免白环/波纹（sat 低）抢位。
        colored = []
        for comp in comps:
            ys = np.array([p[1] for p in comp])
            xs = np.array([p[0] for p in comp])
            mean = rgb[ys, xs].mean(0)
            sat = mean.max() - mean.min()
            if sat > 25:
                colored.append((len(comp), sat, comp))
        if colored:
            colored.sort(key=lambda t: t[0], reverse=True)
            return max(colored[:3], key=lambda t: t[1])[2]
        return comps[0]

    bx0, by0, bx1, by1 = box
    scored = []
    for comp in comps:
        ys = np.array([p[1] for p in comp])
        xs = np.array([p[0] for p in comp])
        overlap = int(((xs >= bx0) & (xs < bx1) & (ys >= by0) & (ys < by1)).sum())
        mean = rgb[ys, xs].mean(0)
        # 以与 ground 框的重叠为主：文字、圆环等框外杂质直接出局。
        scored.append((overlap, len(comp), comp))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return scored[0][2]


def run(args: argparse.Namespace) -> int:
    boxes = _parse_boxes(args.boxes) if args.boxes else []
    if boxes and len(boxes) != len(args.images):
        print(f"error: {len(args.images)} images but {len(boxes)} boxes", file=sys.stderr)
        return 1
    pairs = [(img, boxes[i] if boxes else None) for i, img in enumerate(args.images)]
    if boxes and len(args.images) != len(boxes):
        print(f"error: {len(args.images)} images but {len(boxes)} boxes", file=sys.stderr)
        return 1

    extract_fg = Path(__file__).resolve().parent / "extract_fg.py"
    EXCLUDE_TOL = 35  # 圆底渐变排除容差（extract_fg 默认 24 排不干净渐变）
    for i, (image_path, box) in enumerate(pairs):
        img = np.asarray(Image.open(image_path).convert("RGB")).astype(int)
        if box is not None:
            bx0, by0, bx1, by1 = box
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            radius = args.disc_radius or max(bx1 - bx0, by1 - by0) * 0.8
        else:
            # 无框默认：crop 已把图标裁在画面中央，圆心=图中心；
            # 半径取图内接圆半径的 0.6（图标圆底约占总宽 60%），可 --disc-radius 覆盖。
            h0, w0 = img.shape[:2]
            cx, cy = w0 / 2, h0 / 2
            radius = min(w0, h0) / 2 * 0.6
            if args.disc_radius:
                radius = args.disc_radius
        yy, xx = np.mgrid[0 : img.shape[0], 0 : img.shape[1]]
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        ring = (d > radius * 0.75) & (d < radius * 0.95)
        mean = img[ring].mean(0).round(0).astype(int)
        hexc = "#%02X%02X%02X" % tuple(mean)
        print(f"--- {Path(image_path).stem}: center=({cx:.0f},{cy:.0f}) disc radius≈{radius:.0f} "
              f"{'box=' + str(box) if box else '(auto)'} "
              f"exclude-color={hexc}")

        fg_out = Path(image_path).with_name(f"{Path(image_path).stem}.fg.png")
        h, w = img.shape[:2]
        subprocess.run(
            [
                sys.executable,
                str(extract_fg),
                str(image_path),
                "--region", f"0,0,{w},{h}",
                "--exclude-color", hexc,
                "--exclude-tol", str(EXCLUDE_TOL),
                "-o", str(fg_out),
            ],
            check=True,
            capture_output=True,
        )

        a = np.asarray(Image.open(fg_out).convert("RGBA"))
        alpha = (a[:, :, 3] > 128).astype(np.uint8)
        ink = {(x, y) for y, x in zip(*np.where(alpha))}
        comp = _pick_component(ink, (a.shape[1], a.shape[0]), a[:, :, :3], box)
        if comp is None:
            print(f"  !! no component matched rule '{args.pick}'", file=sys.stderr)
            continue
        clean = np.zeros_like(a)
        ys = [p[1] for p in comp]
        xs = [p[0] for p in comp]
        clean[ys, xs] = a[ys, xs]
        clean[ys, xs, 3] = 255
        out = Image.fromarray(clean, "RGBA").crop((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
        clean_path = Path(image_path).with_name(f"{Path(image_path).stem}.clean.png")
        out.save(clean_path)
        print(f"  -> {clean_path} ({out.size}) fg_px={len(comp)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="图标前景提取封装（裁剪放大 / 提取干净前景）")
    ap.add_argument("images", nargs="+", help="crop --scale 输出的放大图")
    ap.add_argument("--boxes", metavar="X1,Y1,X2,Y2;...",
                    help="可选：ground 在放大图上的精确框，分号分隔，与图片一一对应")
    ap.add_argument("--disc-radius", type=float, default=None, help="圆底半径（放大图像素），缺省自动推断")
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
