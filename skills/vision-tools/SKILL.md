---
name: vision-tools
description: Use the locally installed glance and ground CLIs for image analysis. Use when the user asks to describe, view, answer questions about, or OCR an image, locate an object/region in an image and get pixel coordinates, or mentions glance/ground — and to re-examine an image yourself when a text description of it you were given lacks the detail you need. If the commands are missing, report that the tools are not installed.
---

# vision-tools

The codex-vision-proxy project installs the following CLIs on this machine. They share the same vision config as the proxy (`VISION_API_KEY` / `VISION_BASE_URL` / `VISION_MODEL` / `LANG`) — no extra credentials needed:

- `glance`: image description, Q&A, and OCR
- `ground`: locate targets in an image with natural language and get bounding boxes in original pixel coordinates

## glance

```bash
glance <image>                            # describe the image in detail
glance <image> -q "<question>"            # ask a question about the image
glance <image> --ocr                      # verbatim OCR of all visible text
glance <image> --region X1,Y1,X2,Y2 -q "<question>"  # crop first; ask about the crop only
glance <img1> <img2> [...] -q "<question>"  # several images in ONE call (compare/diff)
```

For comparisons (before/after, two renders, expected vs actual) always pass
both paths to a single glance call — separate calls cannot see both images at
once. Paths are space-separated. Without `-q`, multiple images get a
describe-then-diff answer by default. `--region` accepts exactly one image.

Output language follows the `LANG` setting in the vision config (`zh`/`en`).
`--region` crops locally and uploads only the crop — use it to zoom into small
text or icons that a full-image pass missed (requires the optional `pillow`).

**Never use glance for precise numeric values** — coordinates, offsets,
pixel distances, measurements. Free-text vision answers estimate numbers and
the estimates look confident. For anything numeric: use `ground` first
(its coordinates are calibrated to the original image), and if that is not
enough, compute from the image with code (e.g. Pillow pixel math) instead of
asking glance.

## ground

```bash
ground <image> "<target description>"
```

Output format: `x1: .., y1: .., x2: .., y2: ..` (pixel coordinates in the original image).

## Re-examining an image (follow-up looks)

Sometimes an image reaches you only as a text description — for example a line
starting with `[vision model description]` if the optional proxy is installed,
or a summary someone else wrote. If that description lacks a detail you need
and the image's file path is visible in the conversation (pasted images live
at a `codex-clipboard-*.png` temp path; `view_image` calls name their path
explicitly), look again yourself:

1. `glance <path> -q "<the specific detail you need>"` — targeted follow-up
   question (qualitative details only, never numbers).
2. `ground <path> "<target>"` then `glance <path> --region <that box> -q "..."` —
   locate first, then zoom in to read small text or fine detail. This
   two-step is the reliable way to inspect one element closely.

If the file no longer exists (temp files are cleaned up), say so instead of guessing.

## Notes

- Only PNG / JPEG / GIF / WebP images are supported.
- If `glance`/`ground` are not found, the optional tools were not installed — report this to the user instead of improvising a replacement.
- If the vision API fails, relay the error faithfully; never fabricate image content.

Source repository: https://github.com/Anionex/codex-vision-proxy

If the tools are not installed, see the installation guide: https://github.com/Anionex/codex-vision-proxy/blob/main/AGENT_INSTALL.md
