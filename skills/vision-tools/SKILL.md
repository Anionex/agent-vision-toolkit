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
| Any exact number (color, offset, size) | `ground`, or code over pixels — **never `glance`** |

The last row drives the others: vision-model prose estimates numbers
confidently but unreliably; `ground`'s boxes are calibrated to the original
image, and pixel code (Pillow) is exact.

## glance — ask about an image

```bash
glance <image>                                 # detailed description
glance <image> -q "<question>"                 # targeted question (qualitative only)
glance <image> --ocr                           # verbatim OCR
glance <image> --region X1,Y1,X2,Y2 -q "..."   # zoom into a crop
glance <img1> <img2> -q "..."                  # compare in ONE call
```

Comparisons (before/after, expected vs actual) must pass all paths to a
single call — separate calls cannot see both images. `--region` uploads
only the crop, so small text and icons become readable.

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
`RESTORE.md` — it holds the reuse traps and the ship-vs-hand-write call.

## When you have a description instead of the image

If an image reached you only as text — a description written by a person,
a tool, or another model — and the image's file path is visible in the
conversation, do not reason past a missing detail. Look again yourself:

1. `glance <path> -q "<the specific detail>"` — one qualitative follow-up.
2. `ground <path> "<target>"` then `glance <path> --region <that box> -q "..."` —
   locate, then zoom. The reliable way to inspect one element closely.

If the file no longer exists (temp files get cleaned), say so instead of
guessing.

## Going deeper

- `METHOD.md` — read before any multi-step image work: the universal
  coarse-to-fine looking method.
- `RESTORE.md` — read when reproducing an image as HTML/SVG: inventory
  workflow, trace usage in practice, verification.
- `scripts/pixel_diff.py <original> <rebuilt>` — the verification step for
  anything you build from an image. Prints an overall difference percentage
  plus the worst regions as `x1: ..` boxes you can feed back into
  `glance --region`. Paths here are relative to this skill's own directory.

## Notes

- Only PNG / JPEG / GIF / WebP images are supported.
- If a command is not found, the optional tools were not installed — report
  this to the user instead of improvising a replacement.
- If the vision API fails, relay the error faithfully; never fabricate
  image content.

Source repository: https://github.com/Anionex/codex-vision-proxy

Installation guide: https://github.com/Anionex/codex-vision-proxy/blob/main/AGENT_INSTALL.md
