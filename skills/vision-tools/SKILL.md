---
name: vision-tools
description: Local vision CLIs: glance (describe/ask/OCR an image), ground (locate a target, pixel box), detect (element inventory), trace (image to SVG geometry). Use for any task involving an image — questions, text, locating elements, comparing, rebuilding as HTML/SVG — and to re-check an image yourself when a description you were given lacks a detail.
---

# vision-tools

Four local CLIs that give a text-only agent eyes. They read one shared
vision config (`VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL` /
`LANG`) — no extra credentials.

Pick the tool by the question you are answering:

| Question | Tool |
|---|---|
| "What does this image show / say?" | `glance` |
| "Where is X?" — a thing you can name | `ground` |
| "Where are all the Xs?" — every instance of a kind | `detect` |
| "What is its exact shape, size, offset?" | `trace` |
| "Which colours dominate a region, and which palette value fits it?" | `scripts/dominant_colors.py` |
| A number none of them return — a colour value, the gap between two things | code over the pixels (Pillow) |

`glance` answers what something is; `ground` and `detect` answer where.
You give `ground` a description of a particular thing; you give `detect` a
kind and it enumerates the instances.

Both give real coordinates, but they are not pixel-exact: the box arrives
on a 0-1000 grid and is scaled to your image, so the last pixel or few are
not reliable. That is accurate enough to crop with, to click, to compare
positions against. When a number has to be exact, `trace` derives it from
the actual pixels — offsets, sizes, shapes.

Drop to Pillow only for what none of them return: sampling a colour, or
computing a relation between two things you already located.

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
badge or a small shift is a rounding error to a vision model and exact to
`scripts/pixel_diff.py`. Diff first to get the box, then `glance --region`
that box to read what the change actually is.

## ground — locate a named target

```bash
ground <image> "<target description>"
ground <image> "<target>" --region X1,Y1,X2,Y2
```

Output: `x1: .., y1: .., x2: .., y2: ..` in original-image pixels — with
`--region` too (crop hits are mapped back).

If several boxes come back numbered, your description matched more than
one element rather than picking out a single thing. Narrow it with what
distinguishes the one you mean — its text, its position, the block it sits
in — and ask again.

The box is a handle, not just an answer — it feeds the next call:

```bash
$ ground screenshot.png "the send button"
x1: 1067, y1: 841, x2: 1108, y2: 881
$ glance screenshot.png --region 1067,841,1108,881 -q "is it enabled or greyed out?"
```

That two-step is how you inspect anything too small to survive a
full-image pass.

## detect — find every instance of a kind

```bash
detect <image>                        # every UI element
detect <image> "buttons"              # one kind only
detect <image> --region X1,Y1,X2,Y2   # inside one box
```

You name a particular thing for `ground`; you name a kind for `detect` and
it enumerates the instances. Output is a numbered list with each item's
visible text and box. A full-screen
pass is a fast first draft — counts vary run to run on dense screens. For
completeness, detect the layout blocks first, then `detect --region` each
block.

## trace — exact shape geometry (local, no vision API)

```bash
trace <image>                                  # b/w spline SVG to stdout
trace <image> --polygon                        # boxy diagrams/wireframes
trace <image> --region X1,Y1,X2,Y2 -o out.svg  # crop first
```

Coordinates come from the actual pixels, not a model's estimate. Flat,
high-contrast graphics only; text becomes curves (pair with `--ocr` when
the text matters). Small images are upscaled automatically before tracing,
so a 30px icon traces as readily as a screenshot — size is not a reason to
skip the tool. Before shipping or reusing a traced SVG, read
`references/restore.md` — it holds the reuse traps and the
ship-vs-hand-write call.

## pixel_diff — where two images differ (local, no vision API)

```bash
python3 scripts/pixel_diff.py <a> <b>      # path is relative to this skill dir
```

Prints an overall difference percentage plus the worst regions as `x1: ..`
boxes you can feed straight into `glance --region`. Exact where a vision
model rounds off.

## dominant_colors — a region's palette, and the exact value among candidates (local, no vision API)

```bash
python3 scripts/dominant_colors.py <image> --region X1,Y1,X2,Y2          # top colour clusters + shares
python3 scripts/dominant_colors.py <image> --region X1,Y1,X2,Y2 \
  --candidates '#F9FAFA,#F5F5F5,#F3F3F3,#EDEDED'                        # pick the best candidate
```

A vision model names a colour ("light gray") but not its value. The first
mode downsamples, quantizes, and merges near-duplicates to list the region's
significant colours with the share each owns — the histogram shows which
colour is the background and which is the accent. Given the candidate palette
your label implies, the second mode scores each candidate by how close the
region's pixels are to it and prints the winner. Take the value from here,
never from `glance`'s prose. Paths are relative to this skill's own
directory.

## Work from a copy, not a temp path

If the image lives in a temp directory, before your first tool call on one, copy it somewhere durable and run everything against the copy — that is what keeps the image reachable later:

```bash
cp "<the temp path>" work/shot.png
glance work/shot.png -q "..."
```

Exception: the user asked for the image to stay in a temp folder.

## When you have a description instead of the image

If an image reached you only as text — a description written by a person,
a tool, or another model — and the image's file path is visible in the
conversation, do not reason past a missing detail. Look again yourself:

1. `glance <path> -q "<the specific detail>"` — one qualitative follow-up.
2. `ground <path> "<target>"` then `glance <path> --region <that box> -q "..."` —
   locate, then zoom. The reliable way to inspect one element closely.

If the file no longer exists, say so instead of guessing.

## Coarse to fine — the method behind every task above

For a single question about an image, `glance` is the whole answer. For
anything multi-step, work outside-in:

1. One full-image pass (`glance`, or a description you already have) for
   the layout and an inventory of what is where.
2. For any element that matters, `ground` it, then zoom with
   `glance --region <box> -q "..."`. Full-image passes routinely miss small
   text and icons; a crop puts all the pixels on one detail, so the model
   sees it at effectively higher resolution.
3. Never take a *prose* answer for a pixel-level fact — exact colors, small
   offsets, sizes. Vision models confidently report styling that is not
   there: coloured syntax highlighting in a monochrome code block, a border
   that does not exist. Get the number from `trace`, from a `ground` box, or
   from `pixel_diff`; sample the pixels yourself only for what those cannot
   return.

## Use cases

Each file below is one job, start to finish: when it applies, the call
sequence, and how to tell you got it right.

| The job | Read |
|---|---|
| Rebuild what an image shows (page → HTML, icon/diagram → SVG) — or check a build against its design image | `references/restore.md` |
| Turn a sketch, whiteboard photo, or diagram into a structured artifact (Mermaid, layout skeleton, outline) | `references/sketch.md` |
| Operate a GUI from screenshots — locate, act, verify each step | `references/gui.md` |

## Notes

- Only PNG / JPEG / GIF / WebP images are supported.
- If a command is not found, the optional tools were not installed — report
  this to the user instead of improvising a replacement.
- If the vision API fails, relay the error faithfully; never fabricate
  image content.

Source repository: https://github.com/Anionex/agent-vision-toolkit

Installation guide: https://github.com/Anionex/agent-vision-toolkit/blob/main/AGENT_INSTALL.md
