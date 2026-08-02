<div align="center">

# codex-deepseek-vision

🌐 [**中文**](README_CN.md) ｜ **English**

</div>

If your Codex is already connected to DeepSeek, but you're frustrated that the model has no multimodal ability — it can't see images, and every attempt to look at an image is blocked by the system — this repository offers a way to let a text-only model call Codex's built-in `view_image` without errors. Instead of failing, it returns a detailed description of the image, keeping the text-only model's experience as close as possible to a multimodal one, without introducing extra MCPs, skills, or CLIs, and without the risk of repeated configuration. It also provides an optional vision toolkit that leverages multimodal models for image Q&A, OCR, visual grounding, and more.

All code has been verified in real Codex + DeepSeek sessions. Use cases include but are not limited to: image Q&A, screenshot analysis, Computer Use GUI operation, and multi-step image reasoning.

If the agent you're using isn't Codex, you can also try installing the [visual toolkit](#install-the-codex-skill-optional) from this repository — it provides CLIs that let agents interact with images.

> If this project helps you, feel free to star🌟 & follow～ I'll keep sharing more practical tools and tips.

## Real-world Effects

<p align="center">
  <img src="assets/effect-1.jpg" alt="DeepSeek in Codex answering a style question about a UI screenshot" width="49%">
  <img src="assets/effect-2.jpg" alt="DeepSeek in Codex debugging mismatched UI fields from a screenshot" width="49%">
</p>

*Left: DeepSeek V4 answers a UI style question with similar-style comparisons. Right: DeepSeek V4 debugs a field-name mismatch from a screenshot.*

<p align="center">
  <img src="assets/effect-3.jpg" alt="Multi-round image Q&A with the optional glance CLI" width="49%">
  <img src="assets/effect-4.jpg" alt="DeepSeek V4 playing chess by locating screen elements with glance/ground" width="49%">
</p>

*Left: multi-round image Q&A after installing the optional `glance` CLI. Right: after installing `ground`, DeepSeek V4 locates screen elements to play chess autonomously.*

## Highlights

- **Pasted images and `view_image` both work**: images pasted directly (`message.content`) and images passed when the model calls `view_image` (`function_call_output.output`) are both understood.
- **Parallel multi-image understanding**: multiple images in one request hit the vision model concurrently — N images cost roughly the latency of 1, no waiting image by image.
- **Same image, one call**: descriptions are cached by image sha256, so the same image appearing repeatedly doesn't re-invoke the vision API; cache hits are nearly zero-latency.
- **Optional `glance`**: a concise standalone CLI for image Q&A or OCR, offering more flexible image understanding.
- **Optional `ground`**: locate a target in an image with natural language and get a bounding box in original pixel coordinates.
- **More vision tools may be added later**

## Usage

This repository doesn't provide a universal one-click installer. The recommended way is to hand the repository link to your Codex agent:

> I've already integrated DeepSeek into Codex and it works. Please read this repository's README first, then follow AGENT_INSTALL.md to deploy and verify `view_image` on the current system.

Detailed steps are in the **[Codex Agent Installation Guide](AGENT_INSTALL.md)**. After installation and a Codex restart, just paste an image or let DeepSeek call the built-in `view_image`.

## Prerequisites

- Codex with a working DeepSeek setup
- Python 3.11+
- An OpenAI-compatible vision API that supports `/chat/completions` and `image_url`

## Configuration

Only these env vars are required:

| Variable | Required | Description |
|---|---:|---|
| `VISION_API_KEY` | Yes | API key of the multimodal model |
| `VISION_BASE_URL` | Yes | OpenAI-compatible API base URL |
| `VISION_MODEL` | Yes | Multimodal model name |
| `LANG` | No | Vision model output language: `zh` (Chinese) or `en` (English); default `zh` |

DeepSeek authentication is still sent by Codex and passed through by the proxy, so there's no need to store it again in the env.

## Optional Tool: glance (Recommended)

`glance` is a standalone CLI for asking questions about an image directly, to fill in specific details.

For a global command, let Codex create a wrapper following the install guide. The call then becomes:

```bash
glance screenshot.png -q "What is the dominant color of this image?"
glance screenshot.png --ocr
```

Answer:

```
The dominant colors of this image are **white and light gray, with light blue accents.**
```

```
Username
Password
Login
```

## Optional Tool: ground

`ground` is a standalone CLI for locating objects or regions in an image:

```bash
ground screenshot.png "Send button"
```

```
x1: 1067, y1: 841, x2: 1108, y2: 881
```

It analyzes one full image per call and outputs the target's pixel coordinates in the original image.

## Install the Codex Skill (optional)

One way to install the extra vision tools into Codex is the bundled `vision-tools` skill, which tells Codex what `glance`/`ground` are and how to use them. Install it with the official skills CLI:

```bash
npx skills add Anionex/codex-deepseek-vision --skill vision-tools -a codex -g --copy -y
```

Or copy the folder manually:

```bash
cp -r skills/vision-tools ~/.codex/skills/
```

Restart Codex afterwards.

## How It Works

```text
Codex -> 127.0.0.1:19100 -> your existing DeepSeek upstream
             |
             +-- when the request contains images: vision API -> text description -> image replaced
```

The first model response only asks Codex to call `view_image`. After Codex executes the tool locally, the second request carries the image; the proxy converts image to text on this request path. If the catalog explicitly declares support for `text` only, Codex's handler rejects the tool first, so `image` is appended to the existing entry only in that case.

## FAQ

### After pointing `base_url` at the local proxy, does the proxy also need a DeepSeek API key?

No. Although the network request to the DeepSeek upstream is sent by the proxy process at `127.0.0.1:19100`, the DeepSeek API key is still placed in the `Authorization` header by Codex per your existing configuration, and the proxy forwards that header unchanged to DeepSeek:

```text
Codex (carrying the original Authorization)
  -> 127.0.0.1:19100
  -> DeepSeek upstream (receives Authorization unchanged)
```

So don't modify Codex's existing auth config, and don't store `DEEPSEEK_API_KEY` again in the proxy env. The proxy env only needs `VISION_API_KEY`, `VISION_BASE_URL`, and `VISION_MODEL`.

## File Listing

| File | Purpose |
|---|---|
| `deepseek-vision-proxy.py` | Local image-rewriting proxy and SSE forwarding |
| `vision_client.py` | Vision API client shared by the proxy and `glance` |
| `bin/glance` | Optional image description, Q&A, and OCR CLI |
| `ground.py` / `bin/ground` | Optional image target-grounding CLI |
| `AGENT_INSTALL.md` | Installation and verification steps for Codex agents |
| `tests/test_image_rewrite_shapes.py` | Tests for image structures, concurrency, caching, and failure behavior |
| `tests/smoke_test_proxy.py` | Tests for proxy pass-through, auth, and streaming protocol |
| `tests/test_vision_client.py` | Vision client retry and `glance` tests |
| `tests/test_ground.py` | `ground` coordinate parsing and shared config tests |

## Limitations

- This is an image-to-text proxy; it doesn't hand vision tokens directly to DeepSeek.
- Description quality depends on the configured vision model.
- The cache lives only inside the proxy process and is cleared on restart.

---

Made by [Anionex](https://github.com/Anionex) with codex
