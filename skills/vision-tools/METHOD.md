# Looking methodology

Read this before multi-step image work: UI restoration, detailed screenshot
analysis, or extracting assets from an image. For single questions about an
image, just use `glance` — this file is not needed.

## Coarse to fine

1. Start with one full-image pass (the proxy description if present,
   otherwise `glance`) to get the layout and an inventory of what is where.
2. For any element that matters, locate it with `ground`, then zoom with
   `glance --region <box> -q "..."` — full-image passes routinely miss
   small text and icons; a crop puts all the pixels on one detail, so the
   model sees it at effectively higher resolution.
3. Never trust vision answers for pixel-level facts (exact colors, small
   offsets): sample the pixels with code (Pillow) instead. A vision model
   will confidently report syntax highlighting that a pixel scan proves
   is not there.
4. Verify anything you build from an image (HTML, SVG, a layout) by
   rendering it and pixel-diffing against the original — never by
   comparing descriptions.

## Traced SVG: ship it or reference it

Ship the traced SVG as-is for organic or irregular shapes — that is where
hand-writing loses (a hand-written lookalike measured 26.6% off where the
trace measured 1.8%). For simple geometry (rects, circles, pills) or SVG
that will be edited later, use the trace as a measurement reference
instead: read exact positions, sizes, and radii from its paths, hand-write
clean primitives from them, then pixel-diff your version against the
original so the error stays bounded.
