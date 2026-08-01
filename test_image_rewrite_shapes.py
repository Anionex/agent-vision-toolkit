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
import time


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "deepseek-ua-rewrite-proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._image_desc_from_data_url = lambda *a: "TEST-DESC:" + str(a[0])[:20]
    return mod


def test_shapes():
    mod = _load_proxy()
    data = "data:image/png;base64,AAAA"
    pre = {"type": "message", "role": "user",
           "content": [{"type": "input_text", "text": "hi"}]}

    body_a = {"model": "gpt-5.2", "input": [pre, {
        "type": "message", "role": "user",
        "content": [{"type": "input_image", "image_url": data}]}]}
    body_b = {"model": "gpt-5.2", "input": [pre, {
        "type": "function_call_output", "call_id": "c1",
        "output": [{"type": "input_image", "image_url": data}]}]}
    body_c = {"model": "gpt-5.2", "input": [pre, {
        "type": "function_call_output", "call_id": "c2",
        "output": [{"type": "input_text", "text": "ok"}]}]}

    glance_cmd = []  # repository signature: (parsed, glance_cmd)
    ra = asyncio.run(mod._rewrite_image_inputs(body_a, glance_cmd))
    rb = asyncio.run(mod._rewrite_image_inputs(body_b, glance_cmd))
    rc = asyncio.run(mod._rewrite_image_inputs(body_c, glance_cmd))

    assert ra, "shape A (message.content) was not rewritten"
    assert rb, "shape B (function_call_output.output) was not rewritten"
    assert not rc, "text-only body must stay untouched"
    out = body_b["input"][1]["output"]
    assert out[0]["type"] == "input_text" and "TEST-DESC" in out[0]["text"], out
    print("PASS: shapes A (content) and B (output) rewritten; text-only untouched")


def test_parallel():
    mod = _load_proxy()
    real_desc = mod._image_desc_from_data_url

    def slow_desc(url, *a):
        time.sleep(0.4)
        return "SLOW-DESC"

    mod._image_desc_from_data_url = slow_desc
    try:
        pre = {"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": "hi"}]}
        body = {"model": "gpt-5.2", "input": [pre, {
            "type": "message", "role": "user",
            "content": [
                {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
                {"type": "input_image", "image_url": "data:image/png;base64,BBB"},
                {"type": "input_image", "image_url": "data:image/png;base64,CCC"},
            ]}]}
        t0 = time.time()
        changed = asyncio.run(mod._rewrite_image_inputs(body, []))
        dt = time.time() - t0
        assert changed, "3 images were not rewritten"
        assert dt < 1.1, f"not parallel: 3x0.4s serial would be ~1.2s, got {dt:.2f}s"
        texts = [c["text"] for c in body["input"][1]["content"]]
        assert all(t.startswith("[local vision model description] SLOW-DESC") for t in texts)
        print(f"PASS: 3 images described in parallel ({dt:.2f}s vs ~1.2s serial)")
    finally:
        mod._image_desc_from_data_url = real_desc


if __name__ == "__main__":
    test_shapes()
    test_parallel()
