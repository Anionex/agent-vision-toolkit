---
name: vision-tools
description: Local vision CLIs — glance (ask/describe/OCR an image), ground (locate a target, pixel box), detect (element inventory), trace (image-to-SVG geometry). Use whenever a task involves an image, answering questions about it, reading its text, finding or measuring elements in it, comparing images, or rebuilding it as HTML/SVG — and to re-examine an image yourself when a text description of it you were given lacks a detail you need. If the commands are missing, report that instead of improvising.
---

# vision-tools

Four local CLIs that give a text-only agent eyes. They read one shared
vision config (`VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL` /
`LANG`) — no extra credentials.

Pick the tool by the question you are answering:

| Question | Tool |
|---|---|
| "What does this image show / say?" | `glance` |
| "Where is X?" — one target, one pixel box | `ground` |
| "What is here?" — inventory of elements | `detect` |
| "What is the exact shape?" — vector outlines | `trace` |
| Any exact number (color, offset, size) | code over pixels (Pillow), or `trace` for geometry — **not `glance`, and not `ground`** |

The last row is the one that decides the others, and the dividing line is
not which CLI you call — it is whether the number came from a model or
from the pixels. `ground` runs the same vision model `glance` does; it
just returns a box. That box arrives on a 0-1000 grid and is then scaled
to your image, so its resolution tops out at image-width/1000 — 1px on a
1000px screenshot, ~4px on a 4K one — with the model's own error stacked
on top. Measured against a solid rectangle on a flat background, the
easiest case there is, it still lands a pixel off on some edges.

So `ground` gives you a handle, not a measurement: good enough to crop
with, to click, to know where to sample. When the number itself is the
answer — a hex value, a 2px misalignment, a font size — read it off the
pixels with Pillow, or off `trace`, which is local and deterministic.

## glance — ask about an image

```bash
glance <image>                                 # detailed description
glance <image> -q "<question>"                 # targeted question (qualitative only)
glance <image> --ocr                           # verbatim OCR
glance <image> --region X1,Y1,X2,Y2 -q "..."   # zoom into a crop
glance <img1> <img2> -q "..."                  # compare in ONE call
```

When you do compare with `glance`, pass all paths to one call — separate
calls cannot see both images, so two descriptions compared afterwards are
two hallucination surfaces, not a comparison. `--region` uploads only the
crop, so small text and icons become readable.

But "what changed between these two?" is not a glance question. A one-word
badge or an 18px shift is a rounding error to a vision model and exact to
`scripts/pixel_diff.py`, which reports where the pixels differ and by how
much. Diff first to get the box, then `glance --region` that box to read
what the change actually is.

## ground — locate one target

```bash
ground <image> "<target description>"
ground <image> "<target>" --region X1,Y1,X2,Y2
```

Output: `x1: .., y1: .., x2: .., y2: ..` in original-image pixels — with
`--region` too (crop hits are mapped back). Multiple matches come numbered.

The box is a handle, not just an answer — it feeds the next call:

```bash
$ ground screenshot.png "the send button"
x1: 1067, y1: 841, x2: 1108, y2: 881
$ glance screenshot.png --region 1067,841,1108,881 -q "is it enabled or greyed out?"
```

That two-step is how you inspect anything too small to survive a
full-image pass.

## detect — inventory the elements

```bash
detect <image>                        # every UI element
detect <image> "buttons"              # one category only
detect <image> --region X1,Y1,X2,Y2   # inside one box
```

Numbered list with exact visible text and boxes. A full-screen pass is a
fast first draft — element counts vary run to run on dense screens. For
completeness, detect the layout blocks first, then `detect --region` each
block.

## trace — exact shape geometry (local, no vision API)

```bash
trace <image>                                  # b/w spline SVG to stdout
trace <image> --polygon                        # boxy diagrams/wireframes
trace <image> --region X1,Y1,X2,Y2 -o out.svg  # crop first (auto 2x upscale)
```

Coordinates come from the actual pixels, not a model's estimate. Flat,
high-contrast graphics only; text becomes curves (pair with `--ocr` when
the text matters). Before shipping or reusing a traced SVG, read
`references/restore.md` — it holds the reuse traps and the
ship-vs-hand-write call.

## When you have a description instead of the image

If an image reached you only as text — a description written by a person,
a tool, or another model — and the image's file path is visible in the
conversation, do not reason past a missing detail. Look again yourself:

1. `glance <path> -q "<the specific detail>"` — one qualitative follow-up.
2. `ground <path> "<target>"` then `glance <path> --region <that box> -q "..."` —
   locate, then zoom. The reliable way to inspect one element closely.

If the file no longer exists (temp files get cleaned), say so instead of
guessing.

## Coarse to fine — the method behind every task above

For a single question about an image, `glance` is the whole answer. For
anything multi-step, work outside-in:

1. One full-image pass (`glance`, or a description you already have) for
   the layout and an inventory of what is where.
2. For any element that matters, `ground` it, then zoom with
   `glance --region <box> -q "..."`. Full-image passes routinely miss small
   text and icons; a crop puts all the pixels on one detail, so the model
   sees it at effectively higher resolution.
3. Never take a vision answer for a pixel-level fact — exact colors, small
   offsets, sizes. Sample the pixels with code instead. Vision models
   confidently report styling that is not there: coloured syntax
   highlighting in a monochrome code block, a border that does not exist.

## Use cases

Each file below is one job, start to finish: when it applies, the call
sequence, and how to tell you got it right. Read the one that matches;
skip the rest.

| You are doing this | Read |
|---|---|
| Rebuilding what an image shows — a page as HTML, an icon or diagram as SVG, extracting a visual component | `references/restore.md` |

## Bundled script

`scripts/pixel_diff.py <a> <b>` — compare two images exactly. Any
before/after, design-vs-rebuild, or expected-vs-actual question starts
here. Prints an overall difference percentage plus the worst regions as
`x1: ..` boxes you can feed straight into `glance --region`. Paths here
are relative to this skill's own directory.

Two rules about reading that output, both about not stopping early:

- **A low percentage does not mean a single defect.** The ranking is where
  to start looking, not the list of what is wrong. One cell can hold two
  faults at once — a wrong fill colour is loud enough to hide an 18px
  shift underneath it. Having explained the top region, check whether it
  also moved, resized, or changed shape, and keep working down the
  remaining ranked regions until they come back clean.
- **Never conclude from a description comparison.** Your prose description
  of A against your prose description of B tells you nothing — both came
  from the same model, so its blind spots cancel out instead of showing up.

## Notes

- Only PNG / JPEG / GIF / WebP images are supported.
- If a command is not found, the optional tools were not installed — report
  this to the user instead of improvising a replacement.
- If the vision API fails, relay the error faithfully; never fabricate
  image content.

Source repository: https://github.com/Anionex/codex-vision-proxy

Installation guide: https://github.com/Anionex/codex-vision-proxy/blob/main/AGENT_INSTALL.md
