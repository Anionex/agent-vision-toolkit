#!/usr/bin/env python3
"""Unit tests: fail-safe apply_patch bridge in vision_proxy.py.

Regression input is a real 9router SSE stream captured from a DeepSeek session
(fixtures/apply-patch-real-stream.sse): the upstream emits apply_patch as a
Responses function_call with JSON-wrapped {"patch": ...} arguments, which Codex
0.146.0 rejects with "tool apply_patch invoked with incompatible payload".
The bridge rewrites those frames to custom_tool_call while leaving every other
frame byte-identical (including SSE delimiters).
"""

import importlib.util
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "fixtures", "apply-patch-real-stream.sse")
EXPECTED_PATCH = ("*** Begin Patch\n*** Update File: /tmp/apply-patch-capture/target.txt\n"
                  "@@\n-foo\n+bar\n*** End Patch")

failures = []


def check(name, cond, detail=""):
    if not cond:
        failures.append(name + (" | " + detail if detail else ""))
    print(("PASS " if cond else "FAIL ") + name)


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "vision_proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_apply_patch_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parse_frames(data):
    out = []
    for frame in data.decode("utf-8", errors="replace").split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        data_lines = [line[5:].strip() for line in frame.splitlines() if line.startswith("data:")]
        try:
            payload = json.loads("\n".join(data_lines))
        except Exception:
            payload = None
        out.append((frame.encode(), payload))
    return out


def _rewrite_bytes(mod, raw, seed):
    random.seed(seed)
    pos = 0
    parts = []
    while pos < len(raw):
        n = random.randint(1, 4096)
        parts.append(raw[pos:pos + n])
        pos += n
    state = {"pending": {}, "completed": False}
    buffer = bytearray()
    out = bytearray()
    for part in parts:
        buffer.extend(part)
        while True:
            frame, rest = mod._split_sse_frame(buffer)
            if frame is None:
                break
            buffer = rest
            for out_frame in mod._rewrite_sse_frame(frame, state):
                out.extend(out_frame)
    if buffer:
        for out_frame in mod._rewrite_sse_frame(bytes(buffer), state):
            out.extend(out_frame)
    for item_id, entry in list(state["pending"].items()):
        state["pending"].pop(item_id, None)
        state.setdefault("flushed", set()).add(item_id)
        for out_frame in mod._flush_apply_patch(entry, interrupted=True):
            out.extend(out_frame)
    return bytes(out)


def main():
    mod = _load_proxy()

    # Request side: freeform custom tool -> chat function tool.
    parsed = {"tools": [
        {"type": "custom", "name": "apply_patch", "format": {"type": "grammar", "syntax": "lark"}},
        {"type": "function", "function": {"name": "shell_command", "description": "x"}},
    ]}
    check("request rewrite", mod._rewrite_apply_patch_tool(parsed) is True)
    tool = parsed["tools"][0]
    check("request rewrite -> flat function", tool.get("type") == "function"
          and tool.get("name") == "apply_patch"
          and "function" not in tool
          and tool.get("strict") is False
          and tool["parameters"]["properties"]["input"]["type"] == "string"
          and tool["parameters"]["required"] == ["input"])
    check("request rewrite leaves others", parsed["tools"][1]["function"]["name"] == "shell_command")
    check("request rewrite idempotent", mod._rewrite_apply_patch_tool(parsed) is False)

    # Real stream: 96 events in -> 58 out, bridged and complete.
    raw = open(FIXTURE, "rb").read()
    outputs = [_rewrite_bytes(mod, raw, seed) for seed in range(10)]
    check("deterministic across chunkings", all(o == outputs[0] for o in outputs))
    out = outputs[0]
    in_frames = _parse_frames(raw)
    out_frames = _parse_frames(out)
    check("input 96 / output 58 events", len(in_frames) == 96 and len(out_frames) == 58,
          f"{len(in_frames)}/{len(out_frames)}")
    check("all output frames parse as JSON", all(f[1] is not None for f in out_frames))

    types = [f[1].get("type") for f in out_frames]
    check("no raw function_call apply_patch", all(
        not (f[1].get("type") in ("response.output_item.added", "response.output_item.done")
             and f[1].get("item", {}).get("type") == "function_call"
             and f[1].get("item", {}).get("name") == "apply_patch")
        for f in out_frames))
    check("custom wire events emitted",
          types.count("response.custom_tool_call_input.delta") == 1
          and types.count("response.custom_tool_call_input.done") == 1)
    added = [f[1] for f in out_frames if f[1].get("type") == "response.output_item.added"
             and f[1].get("item", {}).get("name") == "apply_patch"]
    check("custom added with empty input", len(added) == 1 and added[0]["item"]["input"] == "")
    done = [f[1] for f in out_frames if f[1].get("type") == "response.output_item.done"
            and f[1].get("item", {}).get("name") == "apply_patch"]
    check("custom done completed with patch", len(done) == 1
          and done[0]["item"]["type"] == "custom_tool_call"
          and done[0]["item"]["status"] == "completed"
          and done[0]["item"]["input"] == EXPECTED_PATCH)
    check("response.completed last", types[-1] == "response.completed")

    # Passthrough fidelity: every non-bridge input frame must survive byte-identical.
    def is_bridge_input(frame):
        p = frame[1]
        if not isinstance(p, dict):
            return False
        t = p.get("type")
        if t in ("response.function_call_arguments.delta", "response.function_call_arguments.done"):
            return True
        if t in ("response.output_item.added", "response.output_item.done"):
            item = p.get("item") or {}
            return item.get("type") == "function_call" and mod._is_apply_patch_name(item.get("name"))
        return False

    def is_injected(frame):
        p = frame[1]
        if not isinstance(p, dict):
            return False
        t = p.get("type")
        if t in ("response.custom_tool_call_input.delta", "response.custom_tool_call_input.done"):
            return True
        if t in ("response.output_item.added", "response.output_item.done"):
            return (p.get("item") or {}).get("name") == "apply_patch"
        return False

    kept_in = [f for f in in_frames if not is_bridge_input(f)]
    kept_out = [f for f in out_frames if not is_injected(f)]
    check("passthrough frame count", len(kept_in) == len(kept_out), f"{len(kept_in)}/{len(kept_out)}")
    check("passthrough byte-identical", all(a[0] == b[0] for a, b in zip(kept_in, kept_out)))

    # Fail-safe edge cases.
    state = {"pending": {}, "completed": False}
    bad_delta = mod._sse_event("response.function_call_arguments.delta",
                               {"type": "response.function_call_arguments.delta",
                                "item_id": "x", "delta": {"obj": 1}})
    out = mod._rewrite_sse_frame(bad_delta, state)
    check("non-string delta raw passthrough", len(out) == 1 and out[0] == bad_delta)
    state = {"pending": {}, "completed": False}
    garbage = b"not json at all\n\n"
    out = mod._rewrite_sse_frame(garbage, state)
    check("garbage raw passthrough", len(out) == 1 and out[0] == garbage)

    # Non-streaming JSON response rewrite.
    body = json.dumps({"output": [{"type": "function_call", "id": "f", "name": "apply_patch",
                                   "arguments": json.dumps({"patch": EXPECTED_PATCH})}]}).encode()
    rewritten = json.loads(mod._rewrite_apply_patch_response_json(body))
    check("json rewrite", rewritten["output"][0]["type"] == "custom_tool_call"
          and rewritten["output"][0]["input"] == EXPECTED_PATCH)

    # H4: namespaced tools are never captured by the bridge.
    parsed = {"tools": [
        {"type": "function", "name": "my_company.apply_patch", "description": "x", "parameters": {}},
        {"type": "custom", "name": "plugin/apply_patch", "description": "y", "format": {}},
    ]}
    check("namespaced tools untouched", mod._rewrite_apply_patch_tool(parsed) is False
          and parsed["tools"][0]["name"] == "my_company.apply_patch"
          and parsed["tools"][1]["type"] == "custom")

    # H3: nested chat shape is left byte-identical.
    nested = {"type": "function", "function": {"name": "apply_patch", "description": "x"}}
    parsed = {"tools": [nested]}
    check("nested chat shape untouched", mod._rewrite_apply_patch_tool(parsed) is False
          and parsed["tools"][0] is nested)
    # Flat Responses function shape is still normalized (idempotent rewrite).
    flat = {"type": "function", "name": "apply_patch",
            "description": "other", "parameters": {"type": "object", "properties": {}, "required": []}}
    parsed = {"tools": [flat]}
    check("flat function shape rewritten", mod._rewrite_apply_patch_tool(parsed) is True
          and parsed["tools"][0]["description"] == mod.APPLY_PATCH_TOOL_DESCRIPTION)

    # H2: a terminal event must flush a pending call BEFORE the terminal frame
    # so codex still sees it. Codex 0.146 ignores custom_tool_call status, so a
    # complete patch is flushed for execution while a truncated one is dropped
    # (executing it would only pollute tool history with a parse failure).
    def run_interrupted(delta_text):
        state = {"pending": {}, "completed": False}
        frames = []
        frames += mod._rewrite_sse_frame(mod._sse_event("response.output_item.added", {
            "type": "response.output_item.added", "output_index": 0,
            "item": {"id": "fc_x", "type": "function_call", "name": "apply_patch", "arguments": "", "call_id": "cx"}}), state)
        frames += mod._rewrite_sse_frame(mod._sse_event("response.function_call_arguments.delta", {
            "type": "response.function_call_arguments.delta", "item_id": "fc_x", "output_index": 0,
            "delta": delta_text}), state)
        completed = mod._sse_event("response.completed", {"type": "response.completed", "response": {"id": "r"}})
        frames += mod._rewrite_sse_frame(completed, state)
        return frames

    full_frames = run_interrupted(json.dumps({"patch": "*** Begin Patch\n*** End Patch"}))
    done_idx = [i for i, f in enumerate(full_frames)
                if json.loads(next(line[5:].strip() for line in f.decode().splitlines() if line.startswith("data:"))).get("type") == "response.output_item.done"]
    check("terminal flush before completed", len(done_idx) == 1
          and done_idx[0] == len(full_frames) - 2, f"done at {done_idx}")
    check("complete patch flushed for execution", "*** Begin Patch" in full_frames[done_idx[0]].decode()
          and '"status": "completed"' in full_frames[done_idx[0]].decode())

    cut_frames = run_interrupted(json.dumps({"patch": "*** Begin Patch\n- old\n+ ne"}))
    cut_done = [i for i, f in enumerate(cut_frames)
                if json.loads(next(line[5:].strip() for line in f.decode().splitlines() if line.startswith("data:"))).get("type") == "response.output_item.done"
                and "apply_patch" in f.decode()]
    check("truncated patch dropped", cut_done == [] and cut_frames[-1].decode().startswith("event: response.completed"),
          f"unexpected done frames: {cut_done}")

    # H1: buffered rewrite path behaves like the streaming path. (`out` was
    # reused by the fail-safe checks above, so compare against outputs[0].)
    buffered = mod._rewrite_sse_body(raw)
    check("buffered rewrite == streaming rewrite", buffered == outputs[0])

    print("----")
    if failures:
        print("FAILURES:", failures)
        sys.exit(1)
    print("ALL TESTS PASSED")


if __name__ == "__main__":
    main()
