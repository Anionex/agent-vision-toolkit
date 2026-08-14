# Changelog

All notable user-facing changes to agent-vision-toolkit are documented in this file.

## [Unreleased]

### Added

- Let the shared Python vision client call either Chat Completions or Responses APIs, including optional reasoning effort and explicit `store: false` data handling.
- Rewrite OpenAI Chat Completions `image_url` blocks through the existing vision-description pipeline with a host-neutral channel note.

### Fixed

- Send a browser-compatible, configurable User-Agent from the shared Python vision client so Cloudflare-backed OpenAI-compatible endpoints do not reject the default `Python-urllib` signature.

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
