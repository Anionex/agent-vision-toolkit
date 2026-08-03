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

A small icon is a hand-write case, not a no-trace case. A 15-30px stroke
icon is too coarse to ship as a traced outline — the trace returns the
ribbon around the stroke, not its centerline — so the deliverable is a
hand-written `<path stroke=... fill=none>`. Draw it from the trace anyway:
`trace <icon> --polygon` upscales the image for you and returns a handful
of polygon paths whose vertices give every endpoint, corner and stroke
width in pixels. Reading structure off a printed pixel grid instead is
guessing dressed as data — you are eyeballing the same shape with less
precision and no coordinates.

Two traps when reusing traced paths:

- The SVG has a **transparent background** — composite on white before any
  pixel diff or visual check (`rsvg-convert -b white`); transparency reads
  as black in many viewers and gets misdiagnosed as a broken trace.
- Every `<path>` carries a `transform` attribute. When lifting a path into
  another SVG, **copy the transform together with `d`** — holes are
  opposite-winding subpaths and survive standalone extraction, but a
  dropped transform displaces the shape.

**4. Pick every colour from pixels; the model only names it.**

`glance` can tell you a region reads as "light gray", but not whether that is
`#F9FAFA`, `#F5F5F5`, or `#EDEDED` — and a rebuilt page that uses the wrong
gray is visibly off even though both are "light gray". Work colour in three
moves:

1. `glance <image> --region <box> -q "name the colours in this region"` —
   prose labels only. This step names the clusters; it does not measure them.
2. `python3 scripts/dominant_colors.py <image> --region <box>` — downsample,
   quantize, merge near-duplicates, and print the top colour clusters with the
   share each owns. The histogram is the role map: the biggest share is
   usually the background, smaller shares the accents.
3. Map each label to the candidate palette it implies, then let the pixels
   choose:
   `python3 scripts/dominant_colors.py <image> --region <box> --candidates '#F9FAFA,#F5F5F5,#F3F3F3,#EDEDED'`
   — each candidate is scored by a distance filter over the region's pixels
   and the best one wins. Use that hex in the rebuild.

The rule from step 2 still holds: the label comes from the model, the value
from the pixels.

## Verify

Render what you built (Playwright for HTML, rsvg-convert for SVG), then:

```bash
python3 scripts/pixel_diff.py <original.png> <rendered.png>
```

It prints an overall difference percentage and the worst regions as
`x1: .., y1: ..` boxes — the same form `glance --region` and
`detect --region` take, so the top offender goes straight back into a zoom
call. Fix the largest diff, re-render, re-run; the number should drop each
round.

Two rules about reading that output, both about not stopping early:

- **A low percentage does not mean a single defect.** The ranking is where
  to start looking, not the list of what is wrong. One cell can hold two
  faults at once — a wrong fill colour is loud enough to hide a position
  shift underneath it. Having explained the top region, check whether it
  also moved, resized, or changed shape, and keep working down the
  remaining ranked regions until they come back clean.
- **Never conclude from a description comparison.** Your prose description
  of the original against your prose description of the rebuild tells you
  nothing — both came from the same model, so its blind spots cancel out
  instead of showing up.

The script composites transparency on white for you — but if you diff by
hand for any reason, do it yourself.

## Boundaries

Whole screenshots and photos do not trace usefully. Low-contrast art
(watermarks, faint patterns) binarizes away and the trace picks up the
high-contrast content around it instead.

A "0 paths" result means the region binarized to nothing, and it is
recoverable — in order: raise `--scale`, tighten `--region` around the
shape, or pre-invert a light-on-dark image. Reach for `--color` last and
only for genuinely multi-colour art: on anti-aliased input it gives every
grey level its own cluster, so a single icon comes back as dozens of
fragment paths. That output looks like proof the tool cannot handle the
shape, and it is really just the wrong flag.
