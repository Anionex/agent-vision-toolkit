"""Unit and CLI tests for semantic centerline geometry tracing."""

import importlib.machinery
import importlib.util
import math
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_trace():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "trace")
    spec = importlib.util.spec_from_loader(
        "trace_cli", importlib.machinery.SourceFileLoader("trace_cli", path)
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _elements(path):
    root = ET.parse(path).getroot()
    return root, [element.tag.rsplit("}", 1)[-1] for element in root.iter()]


def _run(cli, source, output, *args):
    return subprocess.run(
        [sys.executable, cli, source, *args, "-o", output],
        text=True,
        capture_output=True,
        check=True,
    )


def _antialiased_icon(path, draw_icon, size=96):
    from PIL import Image, ImageDraw

    scale = 4
    image = Image.new("RGB", (size * scale, size * scale), "white")
    draw_icon(ImageDraw.Draw(image), scale)
    image.resize((size, size), Image.Resampling.LANCZOS).save(path)


def main():
    mod = _load_trace()

    svg = (
        '<svg><path d="M0,0 L9,0 Z" fill="#FFFFFF" transform="x"/>'
        '<path d="M1.23456,7.891011 L2,3" fill="#000000"/></svg>'
    )
    stripped = mod.strip_background(svg)
    assert 'fill="#FFFFFF"' not in stripped, "leading white background path must be dropped"
    assert 'fill="#000000"' in stripped

    kept = mod.strip_background('<svg><path d="M0,0" fill="#000000"/></svg>')
    assert 'fill="#000000"' in kept, "non-white first path must survive"

    truncated = mod.truncate_decimals(stripped)
    assert "1.23456" not in truncated and "1.23" in truncated
    assert "7.891011" not in truncated and "7.89" in truncated
    assert mod.rdp([(0, 0), (2, 0.05), (4, 0)], 0.1) == [(0, 0), (4, 0)]
    print("PASS: outline cleanup and geometric simplification helpers")

    try:
        import numpy  # noqa: F401
        from PIL import Image, ImageDraw
    except ImportError:
        print("SKIP: Pillow/numpy not installed; trace geometry is an optional feature")
        return

    cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "bin", "trace")
    with tempfile.TemporaryDirectory() as raw:
        # The core product contract: a magnifier must be semantic geometry, not
        # two contours for every side of each raster stroke.
        search = os.path.join(raw, "search.png")

        def draw_search(draw, scale):
            draw.ellipse((14 * scale, 14 * scale, 64 * scale, 64 * scale),
                         outline="black", width=7 * scale)
            draw.line((58 * scale, 58 * scale, 84 * scale, 84 * scale),
                      fill="black", width=7 * scale)

        _antialiased_icon(search, draw_search)
        search_svg = os.path.join(raw, "search.svg")
        result = _run(cli, search, search_svg)
        root, tags = _elements(search_svg)
        assert tags.count("circle") == 1, tags
        assert tags.count("line") == 1, tags
        assert "path" not in tags, "geometry mode must not fall back to contour paths"
        assert root.attrib["viewBox"] == "0 0 96 96"
        assert "1 circle" in result.stdout and "1 line" in result.stdout
        assert "pixel fit" in result.stdout
        print("PASS: magnifier becomes exactly one circle plus one line")

        # A bent stroke is decomposed into the intended straight segments and
        # junction hooks created by thinning are removed.
        bolt = os.path.join(raw, "bolt.png")

        def draw_bolt(draw, scale):
            draw.line(
                [(67 * scale, 8 * scale), (32 * scale, 50 * scale),
                 (58 * scale, 50 * scale), (36 * scale, 88 * scale)],
                fill="black", width=7 * scale, joint="curve",
            )

        _antialiased_icon(bolt, draw_bolt)
        bolt_svg = os.path.join(raw, "bolt.svg")
        result = _run(cli, bolt, bolt_svg)
        _root, tags = _elements(bolt_svg)
        assert tags.count("line") == 3, tags
        assert "path" not in tags and "polyline" not in tags, tags
        assert "3 straight segments" in result.stdout
        print("PASS: lightning becomes exactly three clean line segments")

        # Collinear branches on either side of a skeleton junction must merge.
        cross = os.path.join(raw, "cross.png")

        def draw_cross(draw, scale):
            draw.line((16 * scale, 48 * scale, 80 * scale, 48 * scale),
                      fill="black", width=8 * scale)
            draw.line((48 * scale, 16 * scale, 48 * scale, 80 * scale),
                      fill="black", width=8 * scale)

        _antialiased_icon(cross, draw_cross)
        cross_svg = os.path.join(raw, "cross.svg")
        _run(cli, cross, cross_svg)
        _root, tags = _elements(cross_svg)
        assert tags.count("line") == 2, tags
        print("PASS: opposite junction branches merge into two full lines")

        # An isolated organic loop is already a meaningful closed trajectory.
        # It must survive as one polygon instead of being carved into unrelated
        # line chords by the straight-run detector.
        cloud = os.path.join(raw, "cloud.png")

        def draw_cloud(draw, scale):
            points = []
            for index in range(240):
                angle = 2 * math.pi * index / 240
                radius = (43 + 7 * math.cos(5 * angle)) * scale
                points.append(
                    (
                        64 * scale + radius * math.cos(angle),
                        64 * scale + radius * math.sin(angle),
                    )
                )
            draw.line(points + [points[0]], fill="black", width=7 * scale, joint="curve")
            draw.line(
                [(49 * scale, 48 * scale), (59 * scale, 64 * scale),
                 (49 * scale, 80 * scale)],
                fill="black", width=7 * scale, joint="curve",
            )
            draw.line((72 * scale, 70 * scale, 91 * scale, 70 * scale),
                      fill="black", width=7 * scale)

        _antialiased_icon(cloud, draw_cloud, size=128)
        cloud_svg = os.path.join(raw, "cloud.svg")
        result = _run(cli, cloud, cloud_svg)
        _root, tags = _elements(cloud_svg)
        assert tags.count("polygon") == 1, tags
        assert tags.count("line") == 3, tags
        assert "4 clean primitives" in result.stdout
        print("PASS: a closed curved outline remains one intact polygon")

        # Curved bodies with attached branches are where greedy global line
        # fitting is weakest. A graph-preserving candidate should win when it
        # materially improves raster fit without changing the simple fixtures.
        curved = os.path.join(raw, "curved-branches.png")

        def draw_curved_branches(draw, scale):
            body = []
            for index in range(220):
                angle = 2 * math.pi * index / 220
                body.append(
                    (
                        (56 + 25 * math.cos(angle) + 2.5 * math.cos(3 * angle)) * scale,
                        (60 + 31 * math.sin(angle)) * scale,
                    )
                )
            draw.line(body + [body[0]], fill="black", width=7 * scale, joint="curve")
            draw.line((56 * scale, 29 * scale, 56 * scale, 88 * scale),
                      fill="black", width=7 * scale)
            draw.line((56 * scale, 62 * scale, 42 * scale, 88 * scale),
                      fill="black", width=7 * scale)
            draw.line((56 * scale, 62 * scale, 70 * scale, 88 * scale),
                      fill="black", width=7 * scale)
            draw.line((43 * scale, 31 * scale, 35 * scale, 21 * scale),
                      fill="black", width=7 * scale)
            draw.line((69 * scale, 31 * scale, 77 * scale, 21 * scale),
                      fill="black", width=7 * scale)

        _antialiased_icon(curved, draw_curved_branches, size=112)
        curved_svg = os.path.join(raw, "curved-branches.svg")
        _run(cli, curved, curved_svg)
        _root, tags = _elements(curved_svg)
        assert tags.count("polyline") >= 4, tags
        _svg, _primitives, _width, fit, _scale = mod.trace_geometry(
            Path(curved), None, None, None, False
        )
        assert fit >= 0.88, fit
        print("PASS: curved branched geometry uses the higher-fidelity graph trace")

        # Compact filled marks are not strokes: thinning collapses them to
        # points and would otherwise discard them. They should remain explicit
        # filled circles alongside ordinary centerline geometry.
        filled = os.path.join(raw, "filled-marks.png")

        def draw_filled_marks(draw, scale):
            draw.line((15 * scale, 20 * scale, 80 * scale, 20 * scale),
                      fill="black", width=7 * scale)
            draw.ellipse((20 * scale, 45 * scale, 36 * scale, 61 * scale),
                         fill="black")
            draw.ellipse((60 * scale, 45 * scale, 76 * scale, 61 * scale),
                         fill="black")

        _antialiased_icon(filled, draw_filled_marks)
        filled_svg = os.path.join(raw, "filled-marks.svg")
        result = _run(cli, filled, filled_svg)
        root, tags = _elements(filled_svg)
        filled_circles = [
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "circle"
            and element.attrib.get("fill") not in {None, "none"}
            and element.attrib.get("stroke") == "none"
        ]
        assert len(filled_circles) == 2, [element.attrib for element in filled_circles]
        assert tags.count("line") == 1, tags
        assert "2 filled circles" in result.stdout
        print("PASS: filled round marks remain semantic filled circles")

        # Auto-upscaling is an analysis detail only: SVG coordinates and viewBox
        # remain in the source image's grid.
        small = os.path.join(raw, "small.png")
        image = Image.new("RGB", (24, 24), "white")
        draw = ImageDraw.Draw(image)
        draw.ellipse((3, 3, 15, 15), outline="black", width=2)
        draw.line((14, 14, 21, 21), fill="black", width=2)
        image.save(small)
        small_svg = os.path.join(raw, "small.svg")
        result = _run(cli, small, small_svg)
        root, tags = _elements(small_svg)
        assert root.attrib["width"] == "24" and root.attrib["viewBox"] == "0 0 24 24"
        assert tags.count("circle") == 1 and tags.count("line") == 1
        assert "analyzed at 1x" not in result.stdout
        print("PASS: small icons upscale internally but keep original SVG coordinates")

        # Region coordinates describe the source image, while the emitted SVG
        # is the cropped graphic's own local coordinate system.
        sheet = os.path.join(raw, "sheet.png")
        canvas = Image.new("RGB", (192, 96), "white")
        with Image.open(search) as icon:
            canvas.paste(icon, (96, 0))
        canvas.save(sheet)
        region_svg = os.path.join(raw, "region.svg")
        _run(cli, sheet, region_svg, "--region", "96,0,192,96")
        root, tags = _elements(region_svg)
        assert root.attrib["viewBox"] == "0 0 96 96"
        assert tags.count("circle") == 1 and tags.count("line") == 1
        print("PASS: --region crops before tracing and emits crop-local coordinates")

        # Border-derived foreground polarity handles light strokes on a dark field.
        inverse = os.path.join(raw, "inverse.png")
        image = Image.new("RGB", (96, 96), "black")
        draw = ImageDraw.Draw(image)
        draw.ellipse((14, 14, 64, 64), outline="white", width=7)
        draw.line((58, 58, 84, 84), fill="white", width=7)
        image.save(inverse)
        inverse_svg = os.path.join(raw, "inverse.svg")
        _run(cli, inverse, inverse_svg)
        _root, tags = _elements(inverse_svg)
        assert tags.count("circle") == 1 and tags.count("line") == 1
        print("PASS: light-on-dark input is detected without manual inversion")

        colored = os.path.join(raw, "colored.png")
        image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        blue = (30, 100, 220, 255)
        draw.ellipse((14, 14, 64, 64), outline=blue, width=7)
        draw.line((58, 58, 84, 84), fill=blue, width=7)
        image.save(colored)
        colored_svg = os.path.join(raw, "colored.svg")
        _run(cli, colored, colored_svg, "--color")
        text = Path(colored_svg).read_text().lower()
        assert 'stroke="#1e64dc"' in text or 'stroke="#1e64dd"' in text, text
        print("PASS: --color samples a transparent icon's foreground color")

        try:
            import vtracer  # noqa: F401
        except ImportError:
            print("SKIP: vtracer not installed; legacy --outline mode is optional")
        else:
            outline_svg = os.path.join(raw, "outline.svg")
            outline = _run(cli, cross, outline_svg, "--outline", "--polygon")
            svg_text = Path(outline_svg).read_text()
            assert "<path" in svg_text and 'fill="#FFFFFF"' not in svg_text
            assert "outline paths" in outline.stdout
            print("PASS: explicit --outline preserves the vtracer silhouette backend")


if __name__ == "__main__":
    main()
