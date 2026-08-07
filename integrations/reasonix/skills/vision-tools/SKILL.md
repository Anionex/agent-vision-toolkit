---
name: vision-tools
description: >-
  Use the installed agent-vision-toolkit CLIs when a Reasonix task involves an
  image: describe or OCR it, locate elements, inventory regions, recover exact
  geometry, crop a box, compare renders, or inspect a long screenshot.
---

# vision-tools for Reasonix

Reasonix keeps a pasted image's local path available to text-only models. Use
the Skill's CLI dispatcher to inspect that path instead of guessing from the
attachment marker.

## Preflight the CLI checkout

Reasonix appends a `## Scripts` section to this skill when it is loaded. Find
the exact absolute path ending in `vision_cli.py` there, then verify that the
toolkit checkout is available:

```bash
python3 "<vision_cli.py path from the Scripts section>" --check
```

Use the machine's Python 3 launcher (`python` or `py -3`) if it does not expose
the interpreter as `python3`.

The Reasonix plugin installs this Skill, not a second copy of the toolkit. The
dispatcher finds the existing toolkit checkout through `glance` on `PATH`, or
from the current working tree. If `--check` fails, clone agent-vision-toolkit
and add its `bin/` directory to `PATH` using the repository's normal CLI setup,
then retry. Do not recreate or vendor the vision commands inside a task.

```bash
git clone https://github.com/Anionex/agent-vision-toolkit.git
export PATH="$PWD/agent-vision-toolkit/bin:$PATH"
```

Run every tool through the dispatcher:

```bash
python3 "<vision_cli.py path from the Scripts section>" <tool> [tool arguments]
```

For a Reasonix context block such as `<image path="...">`, pass the `path`
value exactly as shown. If the user wrote an `@path` reference, pass the
filesystem path without the leading `@`. Quote every filesystem path passed to
the shell, including image, output, HTML, and dispatcher paths.

## Choose the tool by the question

| Question | Tool invocation |
|---|---|
| What does this image show or say? | `glance "<image>"` |
| What matters for the current request? | `glance "<image>" -q "<current intent>"` |
| Transcribe visible text exactly | `glance "<image>" --ocr` |
| Where is one named target? | `ground "<image>" "<target>"` |
| What elements or instances are present, and where? | `detect "<image>" [category]` |
| What is the exact local shape or geometry? | `trace "<image>" [-o "output.svg"]` |
| Cut a known pixel box into a reusable file | `crop "<image>" --region X1,Y1,X2,Y2 [-o "output"]` |
| OCR a scrolling screenshot or chat history | `long-screenshot-ocr "<image>" [-o "output.md"]` |
| Compare two renders at pixel level | `pixel-diff "<before>" "<after>"` |
| Extract a foreground graphic | `extract-fg "<image>" ...` |
| Inspect dominant colors | `dominant-colors "<image>" ...` |
| Render HTML to an image | `html-shot "<file.html>" ...` |

Run the dispatcher with `--list` to print every supported tool name. All
arguments after the tool name are passed through unchanged, so each tool's
normal `--help` remains available.

## Operating rules

1. When the user asks a specific visual question, pass that intent to
   `glance -q`; do not settle for a generic description first.
2. For multiple images that must be compared semantically, pass them to one
   `glance` call so the vision model sees them together.
3. Use `ground` for one named target and `detect` for an inventory. Their boxes
   are suitable for clicking and cropping but can be a few pixels approximate.
4. Use `trace` when shape, offset, or size must come from the actual pixels.
5. Use `crop` and the bundled scripts instead of rewriting their pixel logic in
   an ad hoc Python snippet.
6. After changing a UI or graphic, render the result and inspect it again. Do
   not claim visual completion from source code alone.
7. Report missing files, optional dependencies, and vision API failures
   honestly. Do not invent image contents when a command fails.

The dispatcher inherits the shared `VISION_API_KEY`, `VISION_BASE_URL`,
`VISION_MODEL`, and optional `LANG` configuration used by the rest of the
toolkit. `glance` itself has no third-party Python dependency; other tools keep
their existing optional dependency requirements.
