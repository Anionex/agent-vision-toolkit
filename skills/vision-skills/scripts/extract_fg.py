#!/usr/bin/env python3
"""extract_fg.py — 从截图提取图标/logo 前景（透明 PNG）。

手动模式（2026-08 实测）：搜索区域内取满足判定的像素，整体做 8 邻域连通分量
分析，保留最大连通分量即为前景。背景噪点是散点、图标线条是连续线，连通性
自动分离，无需预先知道主色，抗锯齿全部保留。

用法:
  python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 -o icon.png
  python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --mode dark   # 灰色/黑色线条（logo）
  python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --exclude-color '#E6E6E6'  # 彩色背景干扰
  自动模式（crop --scale 输出、图标居中、浅色圆底；多张可一次传）:
  python3 scripts/extract_fg.py d/icon1.png d/icon2.png       # 圆心=图中心，圆底半径/颜色自动推断
  python3 scripts/extract_fg.py d/icon1.png --disc-radius 60  # 圆底半径兜底
  python3 scripts/extract_fg.py d/icon1.png --boxes "101,84,184,171"  # ground 框校正

输出: 透明背景 PNG（仅前景像素保留原色，其余 alpha=0），打印 bbox / 像素数 / 分量数。
自动模式输出单一图形分量（前 3 大彩色分量中饱和度最高者，白环/文字自动出局）。
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


def process_one(image: str, args: argparse.Namespace) -> int:

    try:
        im = Image.open(image).convert("RGB")
    except Exception as e:
        print(f"error: cannot open {image}: {e}", file=sys.stderr)
        return 1
    w, h = im.size

    auto_mode = args.region is None
    if auto_mode:
        try:
            import numpy as np
        except ImportError:
            print("error: auto mode requires numpy; pass --region instead", file=sys.stderr)
            return 1
        arr = np.asarray(im).astype(int)
        box = None
        if args.boxes:
            try:
                box = tuple(int(v) for v in args.boxes.split(","))
            except ValueError:
                print("error: --boxes must be X1,Y1,X2,Y2", file=sys.stderr)
                return 1
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            radius = args.disc_radius or max(box[2] - box[0], box[3] - box[1]) * 0.8
        else:
            cx, cy = w / 2, h / 2
            radius = args.disc_radius or min(w, h) / 2 * 0.6
        yy, xx = np.mgrid[0:h, 0:w]
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        ring = (dist > radius * 0.75) & (dist < radius * 0.95)
        if ring.sum() == 0:
            print("error: disc ring empty (--disc-radius too small?)", file=sys.stderr)
            return 1
        mean = arr[ring].mean(0).round(0).astype(int)
        auto_excl = tuple(int(v) for v in mean)
        print(f"auto: center=({cx:.0f},{cy:.0f}) disc radius≈{radius:.0f} "
              f"exclude-color=#{auto_excl[0]:02X}{auto_excl[1]:02X}{auto_excl[2]:02X}")
        x1, y1, x2, y2 = 0, 0, w, h
    else:
        auto_excl = None
        box = None
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
    if auto_excl:
        excl = auto_excl
        exclude_tol = 35  # 自动模式：圆底渐变排除容差（默认 24 排不干净渐变）
    elif args.exclude_color:
        v = args.exclude_color.lstrip("#")
        try:
            excl = tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            print("error: --exclude-color must be #RRGGBB", file=sys.stderr)
            return 1
        exclude_tol = args.exclude_tol
    else:
        exclude_tol = args.exclude_tol

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
                if d <= exclude_tol:
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
    if auto_mode:
        # 自动模式：选单一图形分量——前 3 大彩色分量中饱和度最高者（白环/波纹 sat 低出局）。
        colored = []
        for c in kept:
            rs = [px[x1 + p[0], y1 + p[1]][0] for p in c]
            gs = [px[x1 + p[0], y1 + p[1]][1] for p in c]
            bs = [px[x1 + p[0], y1 + p[1]][2] for p in c]
            n = len(c)
            sat = max(sum(rs) / n, sum(gs) / n, sum(bs) / n) - min(sum(rs) / n, sum(gs) / n, sum(bs) / n)
            if sat > 25:
                colored.append((len(c), sat, c))
        if colored:
            colored.sort(key=lambda t: t[0], reverse=True)
            chosen = max(colored[:3], key=lambda t: t[1])[2]
        else:
            chosen = kept[0]
        if box:
            bx0, by0, bx1, by1 = box
            scored = []
            for c in kept:
                overlap = sum(1 for p in c if bx0 <= p[0] < bx1 and by0 <= p[1] < by1)
                scored.append((overlap, len(c), c))
            scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
            chosen = scored[0][2]
        best = chosen
        pad = 0
    else:
        best = [p for c in kept for p in c]
        pad = args.pad
    bx1 = x1 + min(p[0] for p in best) - pad
    by1 = y1 + min(p[1] for p in best) - pad
    bx2 = x1 + max(p[0] for p in best) + 1 + pad
    by2 = y1 + max(p[1] for p in best) + 1 + pad
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

    if args.output:
        dest = Path(args.output)
    elif auto_mode:
        dest = Path(image).with_suffix(".clean.png")
    else:
        dest = Path(image).with_suffix(".fg.png")
    out.save(dest)

    print(f"bbox (原图像素): x1: {bx1}, y1: {by1}, x2: {bx2}, y2: {by2}")
    print(f"前景像素: {len(best)}  保留分量: {len(kept)}/{len(comps)}  最大分量占比: {len(comps[0]) / len(ink) * 100:.0f}%")
    print(f"wrote {dest} ({out.width}x{out.height})")
    return 0
def main() -> int:
    ap = argparse.ArgumentParser(description="从截图区域提取图标/logo 前景（透明 PNG）")
    ap.add_argument("image", nargs="+", help="截图路径（PNG/JPEG/WebP）")
    ap.add_argument("--region", metavar="X1,Y1,X2,Y2",
                    help="手动模式：搜索区域（原图像素，宽松即可）；不传则自动推断（图标居中）")
    ap.add_argument("-o", "--output", default=None,
                    help="输出 PNG 路径（默认 <image-stem>.fg.png；自动模式 <image-stem>.clean.png）")
    ap.add_argument("--disc-radius", type=float, default=None,
                    help="自动模式：圆底半径（像素），缺省 = min(宽,高)/2 × 0.6")
    ap.add_argument("--boxes", default=None, metavar="X1,Y1,X2,Y2",
                    help="自动模式：ground 在放大图上的框，用于圆心/半径校正与分量重叠筛选")
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
    code = 0
    for image in args.image:
        code |= process_one(image, args)
    return code


if __name__ == "__main__":
    sys.exit(main())
