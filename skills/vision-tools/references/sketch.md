# Sketch, whiteboard, or diagram to a structured artifact

**When to use**: a hand-drawn sketch, whiteboard photo, wireframe scribble,
or diagram image must become a structured artifact — a Mermaid or Graphviz
graph, an HTML/layout skeleton, a JSON outline, architecture code. The
deliverable is the drawing's *meaning*: nodes, labels, connections,
containment. When the deliverable is the drawing's *look* — reproduce it
pixel-faithfully — that is `restore.md`.

Tool syntax lives in `SKILL.md`. This file is the sequence and the
pass/fail test.

## Steps

**1. One full pass to classify the drawing.**

`glance <image>` — what kind of drawing this is (flowchart, UI wireframe,
ER diagram, mind map, timeline) and its rough regions. The kind picks the
target format; if the task didn't fix one, choose the format whose
primitives match the drawing — boxes-and-arrows want a flowchart, nested
rectangles want a layout skeleton — rather than forcing one format onto
everything.

**2. Inventory the nodes.**

`detect <image>` for the element list — each item's visible text and box.
On a busy whiteboard, detect the layout clusters first, then
`detect --region` each cluster; full-image passes under-report exactly
where whiteboards are densest.

**3. Transcribe labels verbatim, and admit the unreadable.**

`glance --ocr`, or `glance --region <node box> --ocr` where handwriting is
cramped. Labels enter the artifact letter-for-letter — do not tidy
spelling or expand abbreviations; transcription is this layer's job,
interpretation is the caller's. A label you cannot read is `[unreadable]`,
never a guess: one invented label poisons the whole graph silently.

**4. Recover the edges.**

Connections are where the graph is won or lost. Confirm each suspected
edge with a zoom question:

```bash
glance <image> --region <box spanning both nodes> \
  -q "does a line or arrow connect A and B, and which end has the arrowhead?"
```

On flat screen-drawn diagrams, `trace --polygon` reads the edge list from
geometry: each connector comes back as a path whose endpoints land near
the node boxes they join — match endpoints to the nearest boxes. On
photos, skip trace (see Boundaries) and rely on zoom questions.

Containment needs no vision call at all: a node box inside another node's
box is nesting — read it from the coordinates you already have.

**5. Emit, ordered by position.**

Build the artifact from the node list plus edge list, taking reading order
from coordinates (top-to-bottom, left-to-right) so it lists elements the
way a person reads the drawing. Carry ambiguity out with you: a line that
may or may not connect two nodes becomes a flagged edge (a comment, a
TODO) in the artifact — never a silent yes or no.

## Verify

Pixel-diffing a hand drawing against a rendered artifact is meaningless —
they differ everywhere by design. Verify structure instead:

1. Render the artifact to an image.
2. Rebuild the same inventory from the render (`detect` + OCR) and compare
   *lists*: node count, label set, edge list with directions. A missing
   node or a reversed arrow shows up as a list diff even when both images
   "look right".
3. Smoke check: `glance <original> <render> -q "same nodes and
   connections? name any that differ"` — in ONE call. This cross-checks
   the lists; it does not replace them.

## Boundaries

- Photos (whiteboard, paper) binarize badly — glare and perspective turn
  `trace` output into noise. Geometry recovery from trace is for flat
  screen-drawn diagrams only; on photos, edges come from zoom questions.
- Do not clean up the drawing in imagination: an unlabeled node stays
  unlabeled, a dangling arrow stays dangling. The artifact's value is
  fidelity to what was actually drawn, gaps included.
- Sketches understate intent: an edge missing from the drawing is weak
  evidence it was meant to be absent. Present the recovered graph as what
  the drawing shows, and leave confirming intent to the calling task.
