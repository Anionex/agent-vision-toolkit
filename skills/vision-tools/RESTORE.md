# Rebuilding UI or graphics from a screenshot

Read this only when the task is reproducing what an image shows — a page
as HTML, an icon or diagram as SVG. The universal looking method in
`METHOD.md` still applies; this file adds the restoration-specific calls.

## Inventory first: detect, then refine by region

Start with one full-screen `detect` call for the element inventory rather
than locating elements one by one — a real restoration session spent most
of its time on dozens of single-target calls that one call replaces. A
full-screen pass under-reports on dense screens, so treat it as the
scaffold: `detect --region` each layout block for a complete local list,
then zoom with `glance --region` and sample colors with Pillow.

## Traced SVG: ship it or reference it

Ship the traced SVG as-is for organic or irregular shapes — that is where
hand-writing loses (a hand-written lookalike measured 26.6% off where the
trace measured 1.8%). For simple geometry (rects, circles, pills) or SVG
that will be edited later, use the trace as a measurement reference
instead: read exact positions, sizes, and radii from its paths, hand-write
clean primitives from them, then pixel-diff your version against the
original so the error stays bounded.

## trace in practice

- **Icon / logo / line-art to SVG**: `trace --region <ground box> -o icon.svg`,
  then verify by pixel-diffing the rendered SVG against the original crop,
  never by eyeballing.
- **Diagram / flowchart / wireframe structure**: `--polygon` yields each box
  and arrow as a compact path with exact position and size — layout
  relations become readable text.
- **Measuring elements**: parse the traced paths (or skip SVG and compute
  on pixels directly) rather than asking glance for numbers.

Reuse traps (both have burned a real session):

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

Render what you built (Playwright for HTML, rsvg-convert for SVG) and
pixel-diff against the original screenshot, region by region. Iterate on
the largest diffs first. Never sign off from a description comparison.
