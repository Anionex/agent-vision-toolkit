# Apply-patch fail-safe bridge

Date: 2026-08-05 · Status: validated against a real captured stream

## Problem

Codex 0.146.0 registers `apply_patch` as a Responses **custom/freeform** tool
(PR #21651 deleted the function-style variant). Its router maps:

- `ResponseItem::CustomToolCall` → `ToolPayload::Custom { input }` (accepted by the handler)
- `ResponseItem::FunctionCall` → `ToolPayload::Function { arguments }` (rejected)

The apply_patch handler only accepts `ToolPayload::Custom`, so any
`function_call` named `apply_patch` dies with:

```
tool apply_patch invoked with incompatible payload
```

Real chat providers (DeepSeek through the 9router gateway) cannot emit Responses
`custom` tools: the request is downgraded to a chat function tool, and the model
returns a `function_call` whose arguments are JSON-wrapped — captured in the
fixture as:

```json
{"patch": "*** Begin Patch\n..."}
```

## Fix (fail-safe rules)

All changes live in `vision_proxy.py`; the Codex binary is untouched.

1. **Request side** — rewrite `type:"custom"` `apply_patch` tools into a chat
   `function` tool with a single string `input` argument and a V4A-format
   description, so chat providers know what to emit.
2. **Response side (SSE)** — whitelist-only bridge: only
   `response.output_item.added` / `function_call_arguments.delta|done` /
   `output_item.done` frames whose item is a `function_call` named
   `apply_patch` are transformed into `custom_tool_call` wire (bare `input`).
3. **Default passthrough** — every other frame is forwarded byte-identical,
   *including its `\n\n` delimiter*. Losing the delimiter was the root cause
   of the 2026-08-05 incident: a frame-level parser that stripped separators
   concatenated the whole SSE stream into a few unparseable blobs, and Codex
   saw `stream closed before response.completed`.
4. **Per-frame try/except** — any parse/transform anomaly logs and forwards the
   raw frame; the bridge can never raise into the response path.
5. **Terminal events** — after `response.completed` (or `failed`/`incomplete`)
   everything is raw passthrough; unfinished apply_patch calls at stream end are
   flushed with `status: "incomplete"`.
6. **Non-streaming JSON** responses get the same item rewrite.
7. **Logging** — `handle()` now records full tracebacks (`traceback.format_exc()`)
   instead of a one-line error, so future stream failures are diagnosable.

## Tests

```bash
python3 tests/test_apply_patch_bridge.py
```

The test replays `tests/fixtures/apply-patch-real-stream.sse` (a real 9router
SSE capture: 96 events ending in `response.completed`) through the bridge with
random chunk boundaries and asserts: deterministic output, 96→58 event counts,
a single `custom_tool_call` with the exact unwrapped patch, `response.completed`
last, no raw `function_call` apply_patch left, and every non-bridge frame
byte-identical.

## Deployment

The deployed copy is `~/.local/share/codex-vision-proxy/codex-vision-proxy.py`
(systemd user service `codex-vision-proxy`); pre-swap rollback copy:
`codex-vision-proxy.py.pre-failsafe-20260805`. Local incident write-up:
`docs/INCIDENT-20260805-codex-stream-truncated.md` in that install directory.
