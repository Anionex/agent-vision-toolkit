# Synthetic Telegram long-screenshot OCR demo

This fixture is fully synthetic. The names, messages, dates, release details,
filenames, and identifiers were created for this repository; it contains no
real chat export or user data.

<p align="center">
  <a href="telegram-chat-long.png">
    <img src="telegram-chat-preview.png" alt="Preview of the synthetic English Telegram launch chat" width="680">
  </a>
</p>

## Artifacts

| File | Purpose |
|---|---|
| [`telegram-chat.html`](telegram-chat.html) | Deterministic, offline source for the fictional English conversation. |
| [`telegram-chat-long.png`](telegram-chat-long.png) | The generated 900 x 6000 input screenshot. |
| [`telegram-chat-preview.png`](telegram-chat-preview.png) | A compact README preview cropped from the same synthetic screenshot. |
| [`telegram-chat-ocr.md`](telegram-chat-ocr.md) | Merged Markdown transcript produced by the long-screenshot OCR workflow. |

## Checked-in reference run

The reference run on **August 6, 2026** produced the following result:

| Check | Result |
|---|---:|
| Synthetic source records | 57 |
| Extracted records | 57 |
| OCR chunks | 4 |
| Split boundaries | 3 |
| Fallback overlap | 128 px at 1 boundary |
| Repeated boundary records merged | 2 |
| Differences across speaker, timestamp, body, and reply metadata | **0** |

The source intentionally mixes incoming and outgoing messages, replies, date
and system pills, numbered and bulleted lists, two code blocks, a PDF
attachment, reactions, and a pinned-message event. This exercises both safe
split selection and structured chat merging instead of testing only plain
paragraph OCR.

## Reproduce

From the repository root, first configure the normal `VISION_*` variables,
then run:

```bash
python3 skills/vision-tools/scripts/long_screenshot_ocr.py \
  examples/long-screenshot-ocr/telegram-chat-long.png \
  --mode chat \
  --chunks-dir work/telegram-chat-ocr \
  --jobs 2 \
  -o work/telegram-chat-ocr.md
```

The chunk directory will contain the four images, structured OCR sidecars,
`manifest.json`, and `ocr_audit.md`. Vision-model output can vary, so compare a
new run with the checked-in reference transcript and inspect every boundary the
audit marks for review.

To regenerate the input screenshot from the offline HTML fixture:

```bash
python3 skills/vision-tools/scripts/html_shot.py \
  examples/long-screenshot-ocr/telegram-chat.html \
  --width 900 \
  --height 6000 \
  --wait-ms 100 \
  -o examples/long-screenshot-ocr/telegram-chat-long.png
```
