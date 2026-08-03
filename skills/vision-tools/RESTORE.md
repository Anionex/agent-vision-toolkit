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
