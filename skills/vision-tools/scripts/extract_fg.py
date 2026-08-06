#!/usr/bin/env python3
"""extract_fg.py — Restore 专用：从截图区域提取图标/logo 前景。

方法（2026-08 实测）：搜索区域内取满足判定的像素，整体做 8 邻域连通分量分析，
保留最大连通分量即为前景。背景噪点是散点、图标线条是连续线，连通性自动分离，
无需预先知道主色，抗锯齿全部保留。

用法:
  python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 -o icon.png
  python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --mode dark   # 灰色/黑色线条（logo）
  python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --exclude-color '#E6E6E6'  # 彩色背景干扰

输出: 透明背景 PNG（仅前景像素保留原色，其余 alpha=0），打印 bbox / 像素数 / 分量数。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image


def connected_components(ink: set, w: int, h: int) -> list[list[tuple[int, int]]]:
    """8 邻域连通分量，按大小降序返回。"""
    seen: set = set()
    comps: list[list[tuple[int, int]]] = []
    for p in ink:
        if p in seen:
            continue
        stack = [p]
        seen.add(p)
        comp = []
        while stack:
            cx, cy = stack.pop()
            comp.append((cx, cy))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    q = (cx + dx, cy + dy)
                    if q in seen or q not in ink:
                        continue
                    seen.add(q)
                    stack.append(q)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    return comps


def main() -> int:
    ap = argparse.ArgumentParser(description="从截图区域提取图标/logo 前景（透明 PNG）")
    ap.add_argument("image", help="截图路径（PNG/JPEG/WebP）")
    ap.add_argument("--region", required=True, metavar="X1,Y1,X2,Y2",
                    help="搜索区域（原图像素，宽松即可，须完整包含目标）")
    ap.add_argument("-o", "--output", default=None, help="输出 PNG 路径（默认 <image-stem>.fg.png）")
    ap.add_argument("--mode", choices=("color", "dark"), default="color",
                    help="color=彩色线条（默认）；dark=灰色/黑色线条（logo、图标）")
    ap.add_argument("--sat", type=int, default=12,
                    help="color 模式饱和度阈值（RGB max-min，默认 12）")
    ap.add_argument("--dark", type=int, default=215,
                    help="dark 模式亮度阈值（RGB max，默认 215，即 #BABBBC 级灰线可收）")
    ap.add_argument("--exclude-color", default=None, metavar="#RRGGBB",
                    help="排除与该颜色接近的像素（彩色背景干扰时用）")
    ap.add_argument("--exclude-tol", type=float, default=24,
                    help="--exclude-color 的距离容差（默认 24）")
    ap.add_argument("--pad", type=int, default=3, help="输出 bbox 每边外扩像素（默认 3）")
    ap.add_argument("--no-keep-whites", action="store_true",
                    help="不保留被前景包围的内部白色细节（默认保留）")
    args = ap.parse_args()

    try:
        im = Image.open(args.image).convert("RGB")
    except Exception as e:
        print(f"error: cannot open {args.image}: {e}", file=sys.stderr)
        return 1
    w, h = im.size

    try:
        x1, y1, x2, y2 = (int(v) for v in args.region.split(","))
    except ValueError:
        print("error: --region must be X1,Y1,X2,Y2", file=sys.stderr)
        return 1
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        print("error: empty region", file=sys.stderr)
        return 1

    excl = None
    if args.exclude_color:
        v = args.exclude_color.lstrip("#")
        try:
            excl = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            print("error: --exclude-color must be #RRGGBB", file=sys.stderr)
            return 1

    ink: set = set()
    px = im.load()
    for y in range(y1, y2):
        for x in range(x1, x2):
            r, g, b = px[x, y]
            mx, mn = max(r, g, b), min(r, g, b)
            if args.mode == "color":
                if mx - mn <= args.sat:
                    continue
            else:
                if mx >= args.dark:
                    continue
            if excl is not None:
                d = ((r - excl[0]) ** 2 + (g - excl[1]) ** 2 + (b - excl[2]) ** 2) ** 0.5
                if d <= args.exclude_tol:
                    continue
            ink.add((x - x1, y - y1))

    if not ink:
        print("error: no foreground pixels found in region (raise --sat or lower --dark?)",
              file=sys.stderr)
        return 1

    comps = connected_components(ink, x2 - x1, y2 - y1)
    # 图标可能由多个分离子形状组成（云朵 logo 的 ">_" 与轮廓不相连），
    # 保留所有足够大的分量；噪点散点（远小于最大分量）自动排除。
    min_size = max(len(comps[0]) * 0.02, 8)
    mx0 = [p[0] for p in comps[0]]
    my0 = [p[1] for p in comps[0]]
    main_box = (min(mx0), min(my0), max(mx0), max(my0))

    def overlaps_main(c) -> bool:
        cx = [p[0] for p in c]
        cy = [p[1] for p in c]
        return not (max(cx) < main_box[0] or min(cx) > main_box[2]
                    or max(cy) < main_box[1] or min(cy) > main_box[3])

    kept = [c for c in comps if len(c) >= min_size or overlaps_main(c)]
    best = [p for c in kept for p in c]
    bx1 = x1 + min(p[0] for p in best) - args.pad
    by1 = y1 + min(p[1] for p in best) - args.pad
    bx2 = x1 + max(p[0] for p in best) + 1 + args.pad
    by2 = y1 + max(p[1] for p in best) + 1 + args.pad
    bx1, by1 = max(0, bx1), max(0, by1)
    bx2, by2 = min(w, bx2), min(h, by2)

    out = Image.new("RGBA", (bx2 - bx1, by2 - by1), (0, 0, 0, 0))
    o = out.load()
    for lx, ly in best:
        o[x1 + lx - bx1, y1 + ly - by1] = px[x1 + lx, y1 + ly] + (255,)

    if not args.no_keep_whites:
        # 背景填充：近白像素从 bbox 边缘 flood fill -> 透明（外部背景）；
        # 被彩色前景包围的近白像素（图标内部白色镂空细节）-> 保留纯白。
        w, h = out.width, out.height
        near: set = set()
        for y in range(h):
            for x in range(w):
                r, g, b, a = o[x, y]
                if a == 0:
                    continue
                mx, mn = max(r, g, b), min(r, g, b)
                if mx >= 240 and mx - mn <= 25:
                    near.add((x, y))
        bg: set = set()
        stack = [p for p in near if p[0] == 0 or p[1] == 0 or p[0] == w - 1 or p[1] == h - 1]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in bg:
                continue
            bg.add((cx, cy))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (cx + dx, cy + dy)
                    if q in near and q not in bg:
                        stack.append(q)
        for x, y in bg:
            o[x, y] = (255, 255, 255, 0)
        for x, y in near - bg:
            o[x, y] = (255, 255, 255, 255)

    dest = Path(args.output) if args.output else Path(args.image).with_suffix(".fg.png")
    out.save(dest)

    print(f"bbox (原图像素): x1: {bx1}, y1: {by1}, x2: {bx2}, y2: {by2}")
    print(f"前景像素: {len(best)}  保留分量: {len(kept)}/{len(comps)}  最大分量占比: {len(comps[0]) / len(ink) * 100:.0f}%")
    print(f"wrote {dest} ({out.width}x{out.height})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
