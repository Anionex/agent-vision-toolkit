# Rebuilding UI or graphics from a screenshot

Read this only when the task is reproducing what an image shows — a page
as HTML, an icon or diagram as SVG. The universal looking method in
`METHOD.md` still applies; this file adds the restoration-specific calls.

## Inventory first: detect, then refine by region

Get the element inventory with one full-screen `detect` call. Do not build
it element by element with single-target calls — that costs one vision
call per element for what one call returns. A full-screen pass
under-reports on dense screens, so treat it as the scaffold:
`detect --region` each layout block for a complete local list, then zoom
with `glance --region` and sample colors with Pillow.

## Traced SVG: ship it or reference it

Ship the traced SVG as-is for organic or irregular shapes — do not
hand-write approximations of organic curves; they lose fidelity. For
simple geometry (rects, circles, pills) or SVG that will be edited later,
use the trace as a measurement reference instead: read exact positions,
sizes, and radii from its paths, hand-write clean primitives from them,
then pixel-diff your version against the original so the error stays
bounded.

## trace in practice

- **Icon / logo / line-art to SVG**: `trace --region <ground box> -o icon.svg`,
  then verify by rendering the SVG and running `scripts/pixel_diff.py`
  against the original crop, never by eyeballing.
- **Diagram / flowchart / wireframe structure**: `--polygon` yields each box
  and arrow as a compact path with exact position and size — layout
  relations become readable text.
- **Measuring elements**: parse the traced paths (or skip SVG and compute
  on pixels directly) rather than asking glance for numbers.

Reuse rules:

- The SVG has a **transparent background** — composite on white before any
  pixel diff or visual check (`rsvg-convert -b white`); transparency reads
  as black in many viewers and gets misdiagnosed as a broken trace.
- Every `<path>` carries a `transform` attribute. When lifting a path into
  another SVG, **copy the transform together with `d`** — holes are
  opposite-winding subpaths and survive standalone extraction, but a
  dropped transform displaces the shape.

Boundaries: whole screenshots and photos do not trace usefully; speckle
filtering deletes small features — a "0 paths" result means the region
binarized to nothing (try `--color`, another region, or pre-inverting
dark-theme images). Low-contrast art (watermarks, faint patterns)
binarizes away and the trace picks up the high-contrast content around it
instead.

## Verify the result

Render what you built (Playwright for HTML, rsvg-convert for SVG), then:

```bash
python3 scripts/pixel_diff.py <original.png> <rendered.png>
```

It prints an overall difference percentage and the worst regions as
`x1: .., y1: ..` boxes — the same form `glance --region` and
`detect --region` take, so the top offender goes straight back into a
zoom call. Fix the largest diff, re-render, re-run; the number should
drop each round. Never sign off from a description comparison.

The script composites transparency on white for you, which is the trap
below — but if you diff by hand for any reason, do it yourself.
