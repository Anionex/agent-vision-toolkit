# Rebuilding UI or graphics from a screenshot

Read this only when the task is reproducing what an image shows — a page
as HTML, an icon or diagram as SVG. The universal looking method in
`METHOD.md` still applies; this file adds the restoration-specific calls.

## Traced SVG: ship it or reference it

Ship the traced SVG as-is for organic or irregular shapes — that is where
hand-writing loses (a hand-written lookalike measured 26.6% off where the
trace measured 1.8%). For simple geometry (rects, circles, pills) or SVG
that will be edited later, use the trace as a measurement reference
instead: read exact positions, sizes, and radii from its paths, hand-write
clean primitives from them, then pixel-diff your version against the
original so the error stays bounded.
