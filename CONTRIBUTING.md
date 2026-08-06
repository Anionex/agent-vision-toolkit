# Contributing to agent-vision-toolkit

Thanks for helping improve agent-vision-toolkit. Focused fixes, tests, host integrations, visual workflows, and documentation improvements are welcome.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before You Start

1. Read [README.md](README.md) and, for deployment changes, [AGENT_INSTALL.md](AGENT_INSTALL.md).
2. Search existing issues and pull requests before starting duplicate work.
3. Open an issue before broad architecture changes, new protocol behavior, or new host integrations.
4. Keep changes narrowly scoped. Do not combine unrelated refactors with a fix or feature.

## Project Scope and Invariants

The repository has two layers:

1. Five standalone CLIs (`glance`, `ground`, `detect`, `trace`, and `crop`) plus the `vision-tools` skill.
2. Optional seamless integration through the local proxy or single-file native extensions.

Contributions must preserve these boundaries:

- Do not add a universal one-click installer, uninstaller, migration framework, or configuration-editing framework. Installation remains agent-led and machine-specific.
- Keep the proxy standard-library-only. Optional CLI dependencies must remain isolated from the proxy.
- Preserve ordinary text, model names, and authentication headers exactly. The only fixed display alias is `gpt-5.2` to `deepseek-v4-flash`.
- Keep default SSE forwarding incremental. Buffer only the specific response path that requires compatibility handling.
- Never log request bodies, images, prompts, conversations, API keys, or other credentials.
- Keep Pi / Oh My Pi and OpenCode extensions single-file and self-contained. Failures must remain visible rather than being silently swallowed.
- Keep `glance`, `ground`, and the other CLIs independent from the proxy request path.
- Do not modify the effect images under `assets/` unless the contribution specifically targets those assets.

## Development Setup

- Python 3.11 or newer is required for the Python entry points and core tests.
- Node.js 24 or newer, or Bun, is required only for extension tests.
- Core tests stub their network dependencies; they do not require a real `VISION_API_KEY`.
- Install optional dependencies such as Pillow and vtracer in an isolated environment only when testing the tools that need them.

## Required Verification

Run the core checks after every change:

```bash
python3 -m py_compile vision_proxy.py vision_client.py ground.py detect.py bin/glance bin/trace bin/crop
python3 tests/test_image_rewrite_shapes.py
python3 tests/test_focus_hint.py
python3 tests/test_anthropic_rewrite.py
python3 tests/smoke_test_proxy.py
python3 tests/test_vision_client.py
git diff --check
```

Add the focused check for each changed area:

| Changed area | Additional check |
|---|---|
| `ground.py` / `bin/ground` | `python3 tests/test_ground.py` |
| `detect.py` / `bin/detect` | `python3 tests/test_detect.py` |
| `bin/glance` | `python3 tests/test_glance_region.py` |
| `bin/trace` | `python3 tests/test_trace.py` |
| `bin/crop` | `python3 tests/test_crop.py` |
| `skills/vision-tools/scripts/html_shot.py` | `python3 tests/test_html_shot.py` |
| `skills/vision-tools/scripts/dominant_colors.py` | `python3 tests/test_dominant_colors.py` |
| `skills/vision-tools/scripts/extract_fg.py` | `python3 tests/test_extract_fg.py` |
| `skills/vision-tools/scripts/long_screenshot_ocr.py` | `python3 tests/test_long_screenshot_ocr.py` |
| `extensions/**/*.ts` | `node tests/test_extensions.mjs` |

Some focused tests skip optional CLI cases when their external dependency is unavailable. Mention any skipped check in the pull request.

## Documentation

- Keep `README.md` and `README_CN.md` aligned when changing shared product behavior or setup instructions.
- Preserve the existing product copy and structure; make the smallest patch required for the change.
- Put detailed deployment steps in `AGENT_INSTALL.md`, reusable visual workflows in the skill references, and evaluation evidence in `research/` rather than expanding the README indefinitely.
- Use relative links for repository files so forks and local copies keep working.

## Pull Requests

A pull request should include:

- the concrete problem or use case;
- a concise explanation of the chosen implementation;
- the exact verification commands and results;
- screenshots or fixtures only when they materially verify visual behavior;
- documentation updates for user-visible changes.

Maintainers may ask to split a broad pull request into smaller changes or to move an out-of-scope idea into a discussion first.
