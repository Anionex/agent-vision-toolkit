#!/usr/bin/env python3
"""Unit test: image rewrite covers both request shapes and runs in parallel.

Images reach the proxy in two shapes:
  A) message.content              [{type: input_image, ...}]  (pasted images)
  B) function_call_output.output  [{type: input_image, ...}]  (view_image results)

Regression: only shape A was rewritten, so view_image calls passed raw image
data through to DeepSeek and came back as [Unsupported Image].

Also guards parallelism: N images in one request must be described
concurrently (~1 vision-call duration), not serially (N durations).
"""

import asyncio
import importlib.util
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "codex-vision-proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._image_desc_from_url = lambda url, prompt=None: "TEST-DESC:" + str(url)[:20]
    return mod


def test_shapes():
    mod = _load_proxy()
    data = "data:image/png;base64,AAAA"
    pre = {"type": "message", "role": "user",
           "content": [{"type": "input_text", "text": "hi"}]}

    body_a = {"model": "user-configured-model", "input": [pre, {
        "type": "message", "role": "user",
        "content": [{"type": "input_image", "image_url": data}]}]}
    body_b = {"model": "user-configured-model", "input": [pre, {
        "type": "function_call_output", "call_id": "c1",
        "output": [{"type": "input_image", "image_url": data}]}]}
    body_c = {"model": "user-configured-model", "input": [pre, {
        "type": "function_call_output", "call_id": "c2",
        "output": [{"type": "input_text", "text": "ok"}]}]}

    ra = asyncio.run(mod._rewrite_image_inputs(body_a))
    rb = asyncio.run(mod._rewrite_image_inputs(body_b))
    rc = asyncio.run(mod._rewrite_image_inputs(body_c))

    assert ra, "shape A (message.content) was not rewritten"
    assert rb, "shape B (function_call_output.output) was not rewritten"
    assert not rc, "text-only body must stay untouched"
    out = body_b["input"][1]["output"]
    assert out[0]["text"].startswith("[vision proxy]"), out
    assert out[1]["type"] == "input_text" and "TEST-DESC" in out[1]["text"], out
    print("PASS: shapes A (content) and B (output) rewritten; text-only untouched")


def test_parallel():
    mod = _load_proxy()
    real_desc = mod._image_desc_from_url

    def slow_desc(url, *a):
        time.sleep(0.4)
        return "SLOW-DESC"

    mod._image_desc_from_url = slow_desc
    try:
        pre = {"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": "hi"}]}
        body = {"model": "user-configured-model", "input": [pre, {
            "type": "message", "role": "user",
            "content": [
                {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
                {"type": "input_image", "image_url": "data:image/png;base64,BBB"},
                {"type": "input_image", "image_url": "data:image/png;base64,CCC"},
            ]}]}
        t0 = time.time()
        changed = asyncio.run(mod._rewrite_image_inputs(body))
        dt = time.time() - t0
        assert changed, "3 images were not rewritten"
        assert dt < 1.1, f"not parallel: 3x0.4s serial would be ~1.2s, got {dt:.2f}s"
        texts = [c["text"] for c in body["input"][1]["content"]]
        assert texts[0].startswith("[vision proxy]"), texts[0]
        assert all(t.startswith("[vision model description] SLOW-DESC") for t in texts[1:])
        print(f"PASS: 3 images described in parallel ({dt:.2f}s vs ~1.2s serial)")
    finally:
        mod._image_desc_from_url = real_desc


def test_failure_is_not_forwarded():
    mod = _load_proxy()
    mod._image_desc_from_url = lambda _url, _prompt=None: None
    body = {"input": [{"type": "message", "content": [
        {"type": "input_image", "image_url": "data:image/png;base64,AAA"}
    ]}]}
    try:
        asyncio.run(mod._rewrite_image_inputs(body))
    except mod.VisionError:
        pass
    else:
        raise AssertionError("failed vision calls must raise instead of forwarding the image")
    assert body["input"][0]["content"][0]["type"] == "input_image"
    print("PASS: failed vision call is not converted into an error description")


def test_failure_reason_is_included():
    mod = _load_proxy()

    def boom(_url, _prompt=None):
        raise mod.VisionError("Vision API HTTP 403: balance insufficient")

    mod._image_desc_from_url = boom
    body = {"input": [{"type": "message", "content": [
        {"type": "input_image", "image_url": "data:image/png;base64,AAA"}
    ]}]}
    try:
        asyncio.run(mod._rewrite_image_inputs(body))
    except mod.VisionError as exc:
        assert "balance insufficient" in str(exc), exc
        assert "not forwarded" in str(exc), exc
    else:
        raise AssertionError("failed vision calls must raise")
    print("PASS: failure reason is included in the raised error")


def test_channel_note_lands_once_on_the_first_image():
    mod = _load_proxy()
    data = "data:image/png;base64,AAA"
    # A view_image result arrives before any pasted image: the note belongs to it,
    # because a session that never pastes still needs to learn how the channel works.
    body = {"input": [
        {"type": "function_call_output", "call_id": "c1",
         "output": [{"type": "input_image", "image_url": data}]},
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "and this one"},
                     {"type": "input_image", "image_url": "data:image/png;base64,BBB"}]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))

    first = body["input"][0]["output"]
    assert first[0]["text"].startswith("[vision proxy]"), first
    assert first[1]["text"].startswith("[vision model description] "), first

    notes = [block["text"] for item in body["input"]
             for block in (item.get("content") or item.get("output") or [])
             if block.get("text", "").startswith("[vision proxy]")]
    assert len(notes) == 1, f"the note must appear once per conversation, got {len(notes)}"
    print("PASS: channel note lands once, on the conversation's first image")


if __name__ == "__main__":
    test_shapes()
    test_parallel()
    test_failure_is_not_forwarded()
    test_failure_reason_is_included()
    test_channel_note_lands_once_on_the_first_image()
