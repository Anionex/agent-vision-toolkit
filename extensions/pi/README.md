# vision.ts — Pi / Oh My Pi extension

Gives a text-only model eyes inside [Pi](https://github.com/badlogic/pi-mono) or
[Oh My Pi](https://github.com/can1357/oh-my-pi): a `context` hook replaces every
image block in the outgoing history with a focus-hinted description written by
your configured vision model. Models that natively accept images are left
untouched.

The hook runs at the first step of the request pipeline — before Oh My Pi's
non-vision gate would replace images with a placeholder — and sees the internal
message format, so one file serves both hosts and every provider.

## Install

Copy this one file into the host's extension directory:

```bash
# Pi
mkdir -p ~/.pi/agent/extensions && cp vision.ts ~/.pi/agent/extensions/

# Oh My Pi
mkdir -p ~/.omp/agent/extensions && cp vision.ts ~/.omp/agent/extensions/
```

## Configure

Same env chain as the proxy and CLI tools in this repository — typically
`~/.config/agent-vision-toolkit/env` (permissions `0600`):

```
VISION_API_KEY=...
VISION_BASE_URL=https://your-vision-endpoint/v1
VISION_MODEL=your-vision-model
# optional: LANG=zh  (or en) to pin the description language
```

`$VISION_ENV_FILE`, `%LOCALAPPDATA%/agent-vision-toolkit/env` and a `.env`
in the working directory are also read; later files override earlier ones.

## Behavior

- A pasted image is described under its own message's text; a tool-fetched
  image is described under the assistant's stated reason for looking.
- Descriptions are cached per (image, prompt) for the process lifetime, so
  replayed history costs nothing.
- A failed description is replaced with an explicit failure note — the raw
  image is never forwarded and failures are never silent.
- The rewrite happens on the per-call copy of history; the stored session keeps
  the original images, so switching to a multimodal model restores real vision.
