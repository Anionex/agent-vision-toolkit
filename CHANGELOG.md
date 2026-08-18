# Changelog

All notable user-facing changes to agent-vision-toolkit are documented in this file.

## [Unreleased]

### Changed

- Renamed the bundled agent skill from `vision-tools` to `vision-skills` so the name describes the capability instead of the underlying tools.

### Fixed

- Parse Qwen-family grounding boxes as `x0,y0,x1,y1` while preserving Gemini's `y0,x0,y1,x1` convention, with `VISION_BOX_ORDER` available for custom providers.
- Reject truncated bounding-box JSON instead of silently returning the complete objects that happened to appear before truncation.
- Avoid duplicating `every distinct` and visible-text instructions when callers pass a complete detect category.

## [0.2.0] - 2026-08-14

### Added

- Let the shared Python vision client call either Chat Completions or Responses APIs, including optional reasoning effort and explicit `store: false` data handling.
- Add native Anthropic Messages requests with protocol-specific authentication, image sources, optional thinking control, and text-block response extraction.
- Rewrite OpenAI Chat Completions `image_url` blocks through the existing vision-description pipeline with a host-neutral channel note.
- Add a fast UI restoration workflow for quick, rough first drafts while preserving page hierarchy, visible text, and native controls.
- Add the project landing-page source and link the DeepSeek Harness vision bundle for users who want that integration.

### Changed

- Make upstream egress explicit and resilient: connect directly by default, optionally use a configured HTTP CONNECT proxy, and fail over only when connection establishment fails instead of following ambient system proxy settings.
- Make protocol-specific environment configuration authoritative and keep the existing host authentication and model compatibility behavior intact.

### Fixed

- Send a browser-compatible, configurable User-Agent from the shared Python vision client so Cloudflare-backed OpenAI-compatible endpoints do not reject the default `Python-urllib` signature.
- Honor `Retry-After` and retry Anthropic 529 overload responses.
- Run the `glance` launcher through its interpreter on Windows and preserve `trace` SVG byte output across Windows line-ending behavior.

## [0.1.0] - 2026-08-07

### Added

- Five vision CLIs — `glance`, `ground`, `detect`, `trace`, and `crop` — plus the `vision-tools` agent skill.
- Optional seamless integration: a local proxy for Codex and Claude Code, and single-file native extensions for Pi, Oh My Pi, and OpenCode.
- Pasted-image and tool-fetched image support with task-aware focus hints, parallel multi-image descriptions, per-request caching, and honest failure notes.
- Vision playbooks for long-screenshot OCR, UI restoration, graphic restoration, structure recovery, and GUI operation.
- Community contribution, conduct, support, and security policies.
- Structured issue forms and a pull request template.
- GitHub funding configuration and continuous integration checks.
- A bilingual funding policy and sponsorship-use statement.
