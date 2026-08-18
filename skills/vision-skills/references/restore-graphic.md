# Extracting or rebuilding a graphic asset

**When to use**: the deliverable is an isolated icon, logo, illustration,
decorative mark, or other visual asset as a transparent PNG or SVG. For a full
page or component, read `restore-ui.md` and use this workflow only for the
individual visual assets it identifies.

## Choose the least destructive representation

Use this order:

1. Reuse the original source asset if it already exists in the project.
2. Extract a transparent PNG from the reference when the visual only needs to
   be displayed at the captured size. This preserves the original pixels and
   is the default for screenshot-only brand artwork.
3. Trace an irregular, flat, high-contrast shape when SVG is required.
4. Hand-write simple editable geometry or stroke icons, using the trace or
   pixel measurements as evidence rather than visual estimates.

## Extract a transparent PNG

The final extraction region must be tight around the target ink. A loose crop
that touches neighboring text, borders, or decoration may preserve those
pixels as foreground.

```bash
# Known tight region
python3 scripts/extract_fg.py shot.png \
  --region X1,Y1,X2,Y2 -o asset.png

# Dark or gray line art
python3 scripts/extract_fg.py shot.png \
  --region X1,Y1,X2,Y2 --mode dark -o asset.png

# Center and enlarge a small visual before automatic extraction
crop shot.png --region X1,Y1,X2,Y2 --scale 4 -o work/asset4x.png
python3 scripts/extract_fg.py work/asset4x.png
```

Use `--exclude-color '#RRGGBB'` when a connected background color would
otherwise be retained. If automatic centering is wrong, provide a tighter
region or a target box rather than repeatedly widening the crop.

Inspect the result on both light and dark backgrounds. Confirm complete ink,
clean alpha edges, and no neighboring fragments before reuse.

## Rebuild an SVG only when the deliverable needs one

```bash
trace asset.png -o asset.svg
trace asset.png --polygon -o asset.svg
trace shot.png --region X1,Y1,X2,Y2 -o asset.svg
```

Ship traced paths directly for organic or irregular shapes. For rectangles,
circles, pills, and other simple editable geometry, use the trace as a
measurement and write the simpler SVG yourself.

A small stroke icon is usually a hand-written SVG case, not a no-trace case:
the trace outlines both sides of the raster stroke, while the desired asset is
normally a centerline path with `stroke` and `fill="none"`. Use
`trace --polygon` to recover endpoints, corners, and stroke width, then write
the clean centerline path.

When reusing traced paths:

- Composite transparent SVG output on the intended background before judging
  it; transparent regions may appear black in some viewers.
- Copy each path's `transform` together with its `d` data. Dropping the
  transform displaces otherwise correct geometry.
- Keep opposite-winding subpaths together so holes remain holes.

## Verify

Render the asset at its intended size and compare it with the same tight box
from the reference. Use an overlay or `scripts/pixel_diff.py` to locate missing
parts, contamination, wrong scale, or displaced paths. Judge the asset at its
actual delivery size as well as zoomed in; a technically detailed SVG that
looks worse at 16px is not an improvement.

## Boundaries

- Whole screenshots and photos do not trace usefully.
- Low-contrast art may disappear during binarization. Tighten the region,
  increase scale, or invert light-on-dark input before reaching for color
  tracing.
- Use color tracing only for genuinely multicolor artwork; antialiased single-
  color input can otherwise fragment into many gray-level paths.
- If the visual contains live text, controls, or data-driven content, rebuild
  those parts natively and use the extracted asset only for the static artwork.
