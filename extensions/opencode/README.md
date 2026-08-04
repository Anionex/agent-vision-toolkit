# vision.ts — OpenCode plugin

Gives a text-only model eyes inside [OpenCode](https://github.com/sst/opencode):
the `experimental.chat.messages.transform` hook replaces image file parts in
the outgoing history with focus-hinted descriptions written by your configured
vision model.

## Install

Copy this one file into a plugin directory:

```bash
# per-project
mkdir -p .opencode/plugin && cp vision.ts .opencode/plugin/

# global
mkdir -p ~/.config/opencode/plugin && cp vision.ts ~/.config/opencode/plugin/
```

## Configure

Same env chain as the proxy and CLI tools in this repository — typically
`~/.config/codex-vision-proxy/env` (permissions `0600`):

```
VISION_API_KEY=...
VISION_BASE_URL=https://your-vision-endpoint/v1
VISION_MODEL=your-vision-model
# optional: LANG=zh  (or en) to pin the description language
```

`$CODEX_VISION_PROXY_ENV`, `%LOCALAPPDATA%/codex-vision-proxy/env` and a `.env`
in the working directory are also read; later files override earlier ones.

## Behavior

- Attached/pasted images (data URLs, http URLs, or local paths — local files
  are inlined) are described under their own message's text.
- Descriptions are cached per (image, prompt) for the process lifetime.
- A failed description is replaced with an explicit failure note — the raw
  image is never forwarded and failures are never silent.

## Limitations

- The transform hook does not expose the active model, so the plugin cannot
  detect a multimodal primary by itself. Set `VISION_REWRITE=off` in the
  environment to disable rewriting when you run a vision-capable model.
- Only user-attached image parts are handled in this version; images returned
  inside tool results are not yet rewritten.
