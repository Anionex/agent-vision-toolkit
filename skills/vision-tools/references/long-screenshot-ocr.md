# OCR a long screenshot without losing boundary text

**Use for**: a vertically scrolling screenshot, chat history, long web page,
requirements conversation, log view, or other image that would be downscaled too
aggressively in one vision call. For a PDF or an exported document, prefer a
format-aware document parser instead of screenshot OCR.

## Run the workflow

Work from a durable copy, then choose the content mode:

```bash
# Web pages, documents, logs, tables, and other general content
python3 scripts/long_screenshot_ocr.py work/page.png -o work/page.ocr.md

# Chat histories: preserve message grouping, senders, timestamps, and quotes
python3 scripts/long_screenshot_ocr.py work/chat.png --mode chat -o work/chat.ocr.md
```

Without `-o`, write `<input-stem>.ocr.md`; store chunks, sidecars, the manifest,
and the audit in `<input-stem>_chunks/` unless `--chunks-dir` overrides it.

The script performs four operations:

1. Measure per-row content density and find low-content cut bands near the
   target height.
2. Add pixel overlap only when no safe band exists, so text crossing a risky
   cut appears in both adjacent chunks.
3. Run `glance` on the chunks using the existing `VISION_*` configuration;
   chat mode requests structured messages while general mode uses verbatim OCR.
4. Merge only confident repeated lines or messages and write `manifest.json` plus
   `ocr_audit.md` beside the chunks.

Use `--resume` after an interrupted run. A chunk is reused only when its image,
mode, and custom prompt fingerprint still match:

```bash
python3 scripts/long_screenshot_ocr.py work/chat.png --mode chat --resume -o work/chat.ocr.md
```

Use `--split-only` when you need to inspect or tune the chunks before spending
vision calls:

```bash
python3 scripts/long_screenshot_ocr.py work/page.png --split-only
```

If the defaults produce awkward chunks, rerun with `--target-height`,
`--min-height`, `--max-height`, or `--overlap`. Keep enough height for local
context; do not make tiny OCR tiles unless the source text is unusually small.

## Verify before delivering

1. Read the merged Markdown from top to bottom and compare its opening and
   ending lines with the source.
2. Open `ocr_audit.md`. Review every boundary marked `yes` against the two
   adjacent `chunk_*.png` files. A marked boundary used pixel overlap or fuzzy
   text matching and is not safe to accept blindly.
3. Check sender changes, timestamps, quoted messages, table row breaks, code
   indentation, and paragraphs that cross chunk boundaries.
4. For any doubtful text, run targeted OCR on the relevant chunk or crop:

   ```bash
   glance work/page_chunks/chunk_002.png --ocr "Re-check the final five lines carefully."
   glance work/page_chunks/chunk_002.png --region X1,Y1,X2,Y2 --ocr
   ```

5. Keep visible spelling and punctuation verbatim. Write `[unreadable]` for
   text that remains illegible; do not silently guess or editorially repair it.

## Output contract

- Return the merged `.ocr.md` file as the primary result.
- Keep the chunk directory until verification is complete; it is the evidence
  for ordering and boundary decisions.
- Report unresolved `[unreadable]` text and every boundary that still needs
  human review.
- Do not claim a complete transcription when the first or last screenshot edge
  visibly clips content.
