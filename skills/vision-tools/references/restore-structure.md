# Turning a visual diagram into structured code

**When to use**: the task is converting a sketch, flowchart, architecture
diagram, or whiteboard into Mermaid, Graphviz, JSON, or another structured
representation. The goal is semantic and topological fidelity, not matching
the source renderer pixel for pixel.

## Steps

1. Run one full-image `glance` pass for the diagram type, reading direction,
   major groups, and visual conventions.
2. Use `detect` for the initial node and label inventory. Refine dense groups
   with `detect --region`.
3. Use OCR for labels. Preserve visible spelling, punctuation, and
   abbreviations verbatim; write `[unreadable]` instead of guessing.
4. Locate ambiguous arrows, connectors, legends, and group boundaries with
   `ground` and targeted `glance --region` calls.
5. Build an explicit intermediate inventory before writing the output:
   nodes, labels, groups, edges, directions, and edge labels.
6. Generate the Mermaid, Graphviz, or requested structure from that inventory.

## Verify structure, not pixels

Render the result, inventory it again, and compare these facts with the
reference:

- node count and label set
- group membership and nesting
- edge list and direction
- edge labels and branch conditions
- start/end or input/output roles

Pixel differences are expected because the target renderer chooses its own
fonts, spacing, and routing. A missing node or reversed arrow is a failure even
when the two images look broadly similar; a different curve or gap is not a
failure when the structure is correct.

## Boundaries

- Do not tidy labels, expand abbreviations, or silently repair wording unless
  the user asks for editorial cleanup.
- Do not infer an edge from proximity alone. If its endpoint or direction is
  unclear, zoom into the connector and mark unresolved facts explicitly.
- If the user wants a visual SVG copy rather than structured code, follow
  `restore-graphic.md` instead.
