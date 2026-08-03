# Rebuilding UI or graphics from an image

**When to use**: the task is reproducing what an image shows — a page as
HTML, an icon or diagram as SVG, a visual component lifted out for reuse.
Not for answering questions about an image; that is `glance` alone.

Tool syntax lives in `SKILL.md`. This file is the sequence and the
pass/fail test.

## Steps

**1. Inventory in one pass, then refine by region.**

One full-screen `detect` call gives the element list. Do not build that
list element by element with single-target calls — that spends one vision
call per element for what one call returns. A full-screen pass
under-reports on dense screens, so treat it as the scaffold:
`detect --region` each layout block for a complete local list, then zoom
with `glance --region` and sample colors with Pillow.

**2. Take every number from pixels, never from prose.**

Exact colors, offsets, and sizes are where vision models are confidently
wrong. Sample them with code, or read them off a `trace` — its coordinates
come from the actual pixels.

**3. For each shape, decide: ship the trace, or measure from it.**

Ship the traced SVG as-is for organic or irregular shapes — hand-written
approximations of organic curves lose fidelity. For simple geometry
(rects, circles, pills) or SVG that will be edited later, use the trace as
a measurement reference instead: read exact positions, sizes, and radii
from its paths, then hand-write clean primitives from them.

- **Icon / logo / line-art to SVG**: `trace --region <ground box> -o icon.svg`.
- **Diagram / flowchart / wireframe structure**: `--polygon` yields each box
  and arrow as a compact path with exact position and size — layout
  relations become readable text.
- **Measuring elements**: parse the traced paths (or skip SVG and compute
  on pixels directly) rather than asking `glance` for numbers.

Two traps when reusing traced paths:

- The SVG has a **transparent background** — composite on white before any
  pixel diff or visual check (`rsvg-convert -b white`); transparency reads
  as black in many viewers and gets misdiagnosed as a broken trace.
- Every `<path>` carries a `transform` attribute. When lifting a path into
  another SVG, **copy the transform together with `d`** — holes are
  opposite-winding subpaths and survive standalone extraction, but a
  dropped transform displaces the shape.

## Verify

Render what you built (Playwright for HTML, rsvg-convert for SVG), then:

```bash
python3 scripts/pixel_diff.py <original.png> <rendered.png>
```

It prints an overall difference percentage and the worst regions as
`x1: .., y1: ..` boxes — the same form `glance --region` and
`detect --region` take, so the top offender goes straight back into a zoom
call. Fix the largest diff, re-render, re-run; the number should drop each
round. `SKILL.md` has the two rules for reading that output without
stopping early — they apply here too.

The script composites transparency on white for you — but if you diff by
hand for any reason, do it yourself.

## Boundaries

Whole screenshots and photos do not trace usefully. Speckle filtering
deletes small features — a "0 paths" result means the region binarized to
nothing (try `--color`, another region, or pre-inverting dark-theme
images). Low-contrast art (watermarks, faint patterns) binarizes away and
the trace picks up the high-contrast content around it instead.
