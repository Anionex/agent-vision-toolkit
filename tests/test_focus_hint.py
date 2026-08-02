#!/usr/bin/env python3
"""Unit test: vision prompts are focus-hint aware and mode-routed.

The proxy passes the nearest preceding user text to the vision model so the
description covers what the user actually asked about, picks a scene-specific
instruction (error / ui / chart / default) from that hint, and caches per
(image, prompt) so different hints never reuse a mismatched description.
"""

import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "codex-vision-proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_hint_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(mod):
    prompts = []

    def fake(url, prompt=None):
        prompts.append(prompt)
        return "DESC"

    mod._image_desc_from_url = fake
    return prompts


def test_hint_reaches_vision_prompt():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"input": [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "why does the login page look broken"}]},
        {"type": "function_call_output", "call_id": "c1",
         "output": [{"type": "input_image", "image_url": "data:image/png;base64,AAA"}]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "login page look broken" in prompts[0], prompts[0]
    assert "Do not answer the user's request yourself" in prompts[0]
    print("PASS: user text travels to the vision prompt for view_image outputs")


def test_same_message_text_is_used():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"input": [{
        "type": "message", "role": "user",
        "content": [
            {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
            {"type": "input_text", "text": "what is this traceback about"},
        ]}]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "traceback" in prompts[0], "text after the image in the same message must still be the hint"
    print("PASS: hint works when text follows the image inside one message")


def test_mode_routing():
    mod = _load_proxy()
    cases = {
        "fix this error for me": "error",
        "这个报错是什么原因": "error",
        "还原这个页面布局": "ui",
        "what is the trend in this chart": "chart",
        "look at this photo of my cat": "default",
        "look at this photograph": "default",
        "the guide says to build it": "default",
        "why do these errors appear": "error",
        "": "default",
    }
    for hint, expected in cases.items():
        got = mod._pick_mode(hint)
        assert got == expected, f"{hint!r}: expected {expected}, got {got}"
        assert mod._MODE_PROMPTS[expected] in mod._vision_prompt(hint)
    print("PASS: hints route to error/ui/chart/default modes")


def test_hint_is_truncated():
    mod = _load_proxy()
    prompt = mod._vision_prompt("x" * 5000)
    assert "x" * mod.FOCUS_HINT_MAX_CHARS in prompt
    assert "x" * (mod.FOCUS_HINT_MAX_CHARS + 1) not in prompt
    print("PASS: oversized hints are truncated")


def test_cache_is_per_prompt():
    mod = _load_proxy()
    calls = []
    mod.describe_image = lambda url, prompt=None: calls.append(prompt) or f"DESC-{len(calls)}"
    first = mod._image_desc_from_url("data:image/png;base64,AAA", "prompt one")
    second = mod._image_desc_from_url("data:image/png;base64,AAA", "prompt two")
    again = mod._image_desc_from_url("data:image/png;base64,AAA", "prompt one")
    assert len(calls) == 2, "distinct prompts must not share a cache entry"
    assert first == again, "same (image, prompt) must hit the cache"
    assert first != second
    print("PASS: cache key covers both image and prompt")


def test_rewrite_prefix_is_stable():
    mod = _load_proxy()
    _capture(mod)
    body = {"input": [{
        "type": "message", "role": "user",
        "content": [{"type": "input_image", "image_url": "data:image/png;base64,AAA"}]}]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    text = body["input"][0]["content"][0]["text"]
    assert text.startswith("[vision model description] "), text
    print("PASS: rewritten text keeps the lightweight description prefix")


if __name__ == "__main__":
    test_hint_reaches_vision_prompt()
    test_same_message_text_is_used()
    test_mode_routing()
    test_hint_is_truncated()
    test_cache_is_per_prompt()
    test_rewrite_prefix_is_stable()
