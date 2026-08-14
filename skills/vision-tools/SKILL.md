---
name: vision-tools
description: >-
  Local vision CLIs: glance (describe/ask/OCR an image), ground (locate a
  target, pixel box), detect (element inventory), trace (image to SVG
  geometry), crop (cut a pixel box to a file), and scripts/html_shot.py (HTML
  file to image). Use for any task involving an image — questions, text,
  splitting and transcribing long screenshots or chat histories, locating elements,
  comparing, rebuilding as HTML/SVG, digitizing a sketch or diagram, reading
  values off a chart, operating a GUI from screenshots — and to re-check an
  image yourself when a description you were given lacks a detail.
---

# vision-tools

Five local CLIs that give a text-only agent eyes. They read one shared
vision config (`VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL` /
`LANG`), plus the optional Python-client settings `VISION_API_PROTOCOL`,
`VISION_REASONING_EFFORT`, and `VISION_USER_AGENT` — no extra credentials.

Pick the tool by the question you are answering:

| Question | Tool |
|---|---|
| "What does this image show / say?" | `glance` |
| "Where is X?" — a thing you can name | `ground` |
| "Where are all the Xs?" — every instance of a kind | `detect` |
| "What is its exact shape, size, offset?" | `trace` |
| "Cut this box out as its own image file" | `crop` |
| "OCR this long screenshot / scrolling page / chat history" | `scripts/long_screenshot_ocr.py` |
| "Extract the icon/logo foreground as transparent PNG — manual region or auto (cropped+scaled screenshots)" | `scripts/extract_fg.py` |
| "Turn this HTML file into a screenshot" | `scripts/html_shot.py` |
| "Which colours dominate a region, and which palette value fits it?" | `scripts/dominant_colors.py` |
| A relation none of them return — a gap, a distance between two located things | code over the pixels (Pillow) |

`glance` answers what something is; `ground` and `detect` answer where.
You give `ground` a description of a particular thing; you give `detect` a
kind and it enumerates the instances.

Both give real coordinates, but they are not pixel-exact: the box arrives
on a 0-1000 grid and is scaled to your image, so the last pixel or few are
not reliable. That is accurate enough to crop with, to click, to compare
positions against. When a number has to be exact, `trace` derives it from
the actual pixels — offsets, sizes, shapes.

## Use the provided tools before hand-rolled pixels

Everything this toolkit ships a tool for, call the tool — do not rewrite
it with Pillow in the middle of a task. The CLIs exist so the same pixel
work is not hand-coded differently every time:

- cut a box out of an image → `crop`, not `Image.open(...).crop(...)`
- sample a region's palette → `scripts/dominant_colors.py`
- compare two images → `scripts/pixel_diff.py`
- vectorize to SVG → `trace`
- locate / inventory elements → `ground` / `detect`
- describe / OCR an image → `glance`
- safely split, OCR, and merge a long screenshot → `scripts/long_screenshot_ocr.py`
- HTML file to a screenshot → `scripts/html_shot.py`

Hand-written Pillow is only for what none of them return: a relation
between two things you already located (a gap, a distance), a resize or
overlay, drawing. If you catch yourself writing `.crop()`, `.convert()`,
or histogram code where one of the tools above fits, replace it with the
tool call — same coordinates, same box format, and the output feeds the
next tool directly.

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

For a tall scrolling screenshot, do not send the whole image through one OCR
call and accept the model's downscaling loss. Run the long-screenshot workflow,
which finds low-content cut bands, invokes `glance` on each chunk, uses
structured extraction for chat histories, merges only duplicated overlap, and
writes a boundary audit:

```bash
python3 scripts/long_screenshot_ocr.py work/page.png -o work/page.ocr.md
python3 scripts/long_screenshot_ocr.py work/chat.png --mode chat --resume -o work/chat.ocr.md
```

Read `references/long-screenshot-ocr.md` before using it. It defines the
verification pass for unsafe cuts and chat-message boundaries.

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
`references/restore-graphic.md` — it holds the reuse traps and the
ship-vs-hand-write call.

## crop — cut a pixel box out of an image (local, no vision API)

```bash
crop <image> --region X1,Y1,X2,Y2             # writes <image-stem>.crop.png next to the input
crop <image> --region X1,Y1,X2,Y2 -o out.png
crop <image> --region X1,Y1,X2,Y2 --scale 4   # upscale the cut-out 4x (LANCZOS) first
```

The same X1,Y1,X2,Y2 pixel boxes `ground`/`detect` print, clamped to the
image bounds. Once a box is worth keeping — the same crop is about to feed
`pixel_diff`, `dominant_colors`, and `trace` in turn — cut it to a file
once and reuse it, instead of re-cropping in memory on every call.
`--scale N` upscales the cut-out before writing (default output name becomes
`<image-stem>.crop@Nx.png`): for icons too small for `ground`/`trace` to see
clearly, crop with `--scale 4`, then run `ground`/`trace` on the upscaled
file — coordinates it returns are in the upscaled grid, divide by `N` to map
back to the original image. Requires the optional `pillow`.

## extract_fg — icon foreground as transparent PNG: manual region or auto (local, no vision API)

```bash
# manual: you know the region (and optionally the background colour)
python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 -o icon.png
python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --mode dark          # grey/black line logos
python3 scripts/extract_fg.py shot.png --region X1,Y1,X2,Y2 --exclude-color '#E6E6E6'
# auto: `crop --scale` cut-outs with the icon centred — no region needed
crop shot.png --region X1,Y1,X2,Y2 --scale 4 -o d/icon1.png
python3 scripts/extract_fg.py d/icon1.png d/icon2.png       # writes <stem>.clean.png next to each input
python3 scripts/extract_fg.py d/icon1.png --disc-radius 60
python3 scripts/extract_fg.py d/icon1.png --boxes "101,84,184,171"
```

Manual mode keeps every sufficiently large connected component of the
region (separate logo sub-shapes stay together; specks drop out). Auto mode
takes a `crop --scale` cut-out with the icon centred (disc + glyph): the
disc centre is the image centre, the disc radius defaults to
`min(w,h)/2 * 0.6`, and the disc colour is sampled from a ring around the
centre; that colour is excluded and the glyph is picked as the most
saturated among the three largest coloured components (white rings,
ripples, and text fall away), output as a 1:1 transparent PNG. When auto
inference fails, override the radius with `--disc-radius`, or pass a
`ground` box (in the upscaled grid) as `--boxes` to recentre and re-filter
by overlap. Multiple images may be passed at once (auto mode).
Requires the optional `pillow` (and `numpy` for auto mode).

## html_shot — render an HTML file to an image (local, needs a Chrome-family browser)

```bash
python3 scripts/html_shot.py page.html                      # writes page.png, 1280x800
python3 scripts/html_shot.py page.html --width 1440 --height 900 -o page.png
python3 scripts/html_shot.py page.html --scale 2            # 2x pixels: small text stays readable
```

The visual-alignment loop: write HTML, screenshot it at the reference
viewport, then compare it with the design. Use `pixel_diff` to locate
material differences, not to chase a zero-difference score. Rendering
happens in headless Chrome/Chromium/Edge — no Python dependencies. Only the
viewport is captured, so pass `--height` for pages taller than the window;
`--wait-ms N` pauses for fonts, images, or animation before capturing.
Paths are relative to this skill's own directory.

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
   sees it at effectively higher resolution. When the same box will be
   checked more than once, cut it to a file first with `crop`.
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
| OCR a long screenshot, scrolling page, or chat history without losing text at chunk boundaries | `references/long-screenshot-ocr.md` |
| Rebuild a page or component as HTML/CSS, including a roughly three-minute fast approximation mode, or align an existing UI with its reference image | `references/restore-ui.md` |
| Extract or rebuild an icon, logo, illustration, or other isolated graphic as transparent PNG/SVG | `references/restore-graphic.md` |
| Turn a sketch, diagram, or whiteboard into Mermaid, Graphviz, or another structured representation | `references/restore-structure.md` |
| Operate a GUI from screenshots — locate, act, verify each step | `references/gui.md` |

## Notes

- Only PNG / JPEG / GIF / WebP images are supported.
- If a command is not found, the optional tools were not installed — report
  this to the user instead of improvising a replacement.
- If the vision API fails, relay the error faithfully; never fabricate
  image content.

Source repository: https://github.com/Anionex/agent-vision-toolkit

Installation guide: https://github.com/Anionex/agent-vision-toolkit/blob/main/AGENT_INSTALL.md
