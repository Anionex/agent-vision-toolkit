#!/usr/bin/env python3
"""dominant_colors: a region's significant colours, and the exact value among a candidate palette.

Two halves of one job. First you extract the region's palette -- downsample,
quantize, merge near-duplicates -- so you can see which colours are actually
there and how much of the region each one owns. That share histogram is the
role map: a background takes a big share, an accent a small one.

A vision model (glance) names those clusters in prose ("white", "light gray",
"orange") but not their values. So for the value itself you supply the
candidate palette your label implies ("light gray" -> #F9FAFA / #F5F5F5 /
#F3F3F3 / #EDEDED) and this script decides from the pixels: each candidate is
scored by a distance filter over the region's pixels, and the best one wins.
The label comes from the model; the number always comes from here.
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None
    ImageChops = None


def load_rgb(path: Path) -> "Image.Image":
    # Composite transparency on white the way a viewer would; unflattened
    # alpha reads as black and skews every colour statistic.
    image = Image.open(path)
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        canvas = Image.new("RGB", image.size, "white")
        canvas.paste(image, mask=image.split()[-1])
        image = canvas
    else:
        image = image.convert("RGB")
    return image


def parse_region(region: str, width: int, height: int) -> tuple[int, int, int, int]:
    try:
        x1, y1, x2, y2 = (int(v) for v in region.split(","))
    except ValueError:
        raise ValueError("--region expects four integers: X1,Y1,X2,Y2 (pixels)") from None
    box = (max(0, min(x1, x2)), max(0, min(y1, y2)),
           min(width, max(x1, x2)), min(height, max(y1, y2)))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"--region {region} is empty after clamping to {width}x{height}")
    return box


def hex_of(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def parse_hex(text: str) -> tuple[int, int, int]:
    value = text.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"invalid colour {text!r}: expected #RRGGBB")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def chebyshev(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(x - y) for x, y in zip(a, b))


def bar(share: float, max_share: float, width: int = 20) -> str:
    fill = round(share / max_share * width) if max_share else 0
    return "#" * fill


class _Cluster:
    __slots__ = ("rgb", "count")

    def __init__(self, rgb: tuple[int, int, int], count: int) -> None:
        self.rgb = rgb
        self.count = count


def extract(image: "Image.Image", box: tuple[int, int, int, int], top: int,
            quantize_k: int, max_pixels: int, merge_tol: int) -> list[_Cluster]:
    """Downsample, quantize, merge near-duplicates; return clusters sorted by count."""
    crop = image.crop(box)
    width, height = crop.size
    scale = min(1.0, max_pixels / max(width, height))
    if scale < 1.0:
        crop = crop.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    quantized = crop.quantize(colors=quantize_k, method=Image.MEDIANCUT)
    palette = quantized.getpalette()
    clusters: list[_Cluster] = []
    for count, index in sorted(quantized.getcolors(maxcolors=quantize_k), reverse=True):
        rgb = (palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2])
        for existing in clusters:
            if chebyshev(rgb, existing.rgb) <= merge_tol:
                total = existing.count + count
                existing.rgb = tuple(
                    round((existing.rgb[i] * existing.count + rgb[i] * count) / total)
                    for i in range(3))
                existing.count = total
                break
        else:
            clusters.append(_Cluster(rgb, count))
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


def pick(image: "Image.Image", box: tuple[int, int, int, int], candidates: list[str],
         tol: int) -> tuple[list[dict], dict, dict]:
    """Score each candidate by how close the region's pixels are to it."""
    crop = image.crop(box)
    width, height = crop.size
    total = width * height
    bands = crop.split()
    rows = []
    for text in candidates:
        rgb = parse_hex(text)
        farthest = None
        for band, value in zip(bands, rgb):
            diff = ImageChops.difference(band, Image.new("L", (width, height), value))
            farthest = diff if farthest is None else ImageChops.lighter(farthest, diff)
        histogram = farthest.histogram()
        mean_distance = sum(i * count for i, count in enumerate(histogram)) / total
        hard = sum(count for i, count in enumerate(histogram) if i <= tol)
        # Soft support: pixels closer to the candidate weigh more, so a match
        # is not a binary in/out -- a candidate exactly on the colour wins over
        # a near neighbour that is also inside the tolerance.
        weighted = sum(max(0, tol - i) * count for i, count in enumerate(histogram))
        rows.append({"text": text, "rgb": rgb, "mean_distance": mean_distance,
                     "hard": hard, "weighted": weighted,
                     "share": hard / total * 100})
    winner = max(rows, key=lambda r: (r["weighted"], r["hard"]))
    closest = min(rows, key=lambda r: r["mean_distance"])
    return rows, winner, closest


def format_extract(clusters: list[_Cluster], top: int, box: tuple[int, int, int, int],
                   merge_tol: int) -> list[str]:
    total = sum(c.count for c in clusters)
    if not total:
        return ["(region has no pixels)"]
    width = box[2] - box[0]
    height = box[3] - box[1]
    max_share = max(c.count / total for c in clusters) * 100
    lines = [f"region {box[0]},{box[1]},{box[2]},{box[3]} - {width}x{height} px",
             f"top {top} of {len(clusters)} clusters (merged at distance <= {merge_tol}):"]
    for cluster in clusters[:top]:
        share = cluster.count / total * 100
        lines.append(f"{hex_of(cluster.rgb)}  {share:5.1f}%  {bar(share, max_share)}")
    return lines


def format_pick(rows: list[dict], winner: dict, closest: dict,
                box: tuple[int, int, int, int], tol: int) -> list[str]:
    width = box[2] - box[0]
    height = box[3] - box[1]
    total = width * height
    max_share = max(r["share"] for r in rows) or 1.0
    max_wt = max(r["weighted"] for r in rows)
    lines = [f"region {box[0]},{box[1]},{box[2]},{box[3]} - {width}x{height} px ({total} px sampled)",
             "candidate   share   mean_d  wt    bar"]
    for row in rows:
        mark = "*" if row is winner else " "
        wt = (row["weighted"] / max_wt * 100) if max_wt else 0.0
        lines.append(f"{mark}{row['text']:<9} {row['share']:5.1f}%  {row['mean_distance']:4.1f}  "
                     f"{wt:4.0f}%  "
                     f"{bar(row['share'], max_share)}")
    if winner["hard"] == 0:
        lines.append(f"note: no candidate is within distance <= {tol} of the region; "
                     f"closest by mean distance is {closest['text']}")
    else:
        lines.append(f"winner: {winner['text']} (* in table) - wt is soft-match closeness, "
                     f"so the winner need not have the highest share; "
                     f"{winner['share']:.1f}% of region pixels within distance <= {tol}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dominant_colors",
        description="Extract a region's significant colours, or pick the concrete value among a candidate palette",
    )
    parser.add_argument("image", type=Path, help="the image")
    parser.add_argument("--region", metavar="X1,Y1,X2,Y2",
                        help="restrict to this pixel box (e.g. from ground); default: whole image")
    parser.add_argument("--candidates", metavar="LIST",
                        help="pick mode: comma-separated candidate palette, e.g. #F9FAFA,#F5F5F5,#F3F3F3,#EDEDED")
    parser.add_argument("--top", type=int, default=5, help="how many significant clusters to show (default: 5)")
    parser.add_argument("--quantize", type=int, default=16,
                        help="palette size before merging near-duplicates (default: 16)")
    parser.add_argument("--max-pixels", type=int, default=96,
                        help="downsample the crop to at most this on the long side (default: 96)")
    parser.add_argument("--merge-tol", type=int, default=8,
                        help="merge clusters whose centres are within this per-channel distance (default: 8)")
    parser.add_argument("--tol", type=int, default=16,
                        help="pick mode: per-channel distance for 'matches this candidate' (default: 16)")
    args = parser.parse_args()

    if Image is None:
        parser.exit(1, "dominant_colors: requires Pillow; install the optional dependency pillow first\n")
    path = args.image.expanduser()
    if not path.is_file():
        parser.exit(1, f"dominant_colors: image not found: {path}\n")
    try:
        image = load_rgb(path)
        width, height = image.size
        box = parse_region(args.region, width, height) if args.region else (0, 0, width, height)
        if args.candidates:
            candidates = [candidate.strip() for candidate in args.candidates.split(",") if candidate.strip()]
            if not candidates:
                parser.exit(1, "dominant_colors: --candidates needs at least one #RRGGBB\n")
            rows, winner, closest = pick(image, box, candidates, args.tol)
            print("\n".join(format_pick(rows, winner, closest, box, args.tol)))
        else:
            clusters = extract(image, box, args.top, args.quantize, args.max_pixels, args.merge_tol)
            print("\n".join(format_extract(clusters, args.top, box, args.merge_tol)))
    except ValueError as exc:
        parser.exit(1, f"dominant_colors: {exc}\n")


if __name__ == "__main__":
    main()
