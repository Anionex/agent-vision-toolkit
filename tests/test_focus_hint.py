#!/usr/bin/env python3
"""Unit test: vision prompts are focus-hint aware.

The proxy passes the nearest preceding user text to the vision model so the
description covers what the user actually asked about, and caches per
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


def test_prompt_always_asks_for_full_description():
    mod = _load_proxy()
    for hint in ("这个报错是什么原因", "还原这个页面布局", ""):
        assert mod._DESCRIBE_PROMPT in mod._vision_prompt(hint)
    print("PASS: every hint gets the same describe-and-transcribe instruction")


def test_hint_is_truncated_keeping_the_tail():
    mod = _load_proxy()
    prompt = mod._vision_prompt("HEAD-LOG " + "x" * mod.FOCUS_HINT_MAX_CHARS + " TAIL-QUESTION")
    assert "TAIL-QUESTION" in prompt, "the question at the end of a long message must survive"
    assert "HEAD-LOG" not in prompt
    assert "x" * (mod.FOCUS_HINT_MAX_CHARS + 1) not in prompt
    print("PASS: oversized hints keep the tail, where the question lives")


def test_view_image_uses_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"input": [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "修复登录页样式"}]},
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "我看一下失败截图确认按钮颜色"}]},
        {"type": "function_call", "name": "view_image", "call_id": "c1",
         "arguments": "{\"path\": \"/tmp/a.png\"}"},
        {"type": "function_call_output", "call_id": "c1",
         "output": [{"type": "input_image", "image_url": "data:image/png;base64,AAA"}]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "确认按钮颜色" in prompts[0], prompts[0]
    assert "decided to view" in prompts[0]
    assert "修复登录页样式" not in prompts[0], "assistant intent replaces, not augments, the user text"
    print("PASS: tool-fetched images ride the assistant's stated intent")


def test_new_user_turn_resets_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"input": [
        {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": "上一轮的旧意图"}]},
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "看看这个图表的趋势"}]},
        {"type": "function_call_output", "call_id": "c1",
         "output": [{"type": "input_image", "image_url": "data:image/png;base64,AAA"}]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "图表的趋势" in prompts[0], prompts[0]
    assert "旧意图" not in prompts[0], "intent from before the latest user turn is stale"
    print("PASS: a new user turn invalidates earlier assistant intent")


def test_silent_paste_gets_no_hint():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"input": [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "帮我还原这个页面"}]},
        {"type": "message", "role": "user",
         "content": [
             {"type": "input_text", "text": '<image name=[Image #1] path="/tmp/codex-clipboard-x.png">'},
             {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
             {"type": "input_text", "text": "</image>"},
         ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "know which details matter most" not in prompts[0], (
        "a silent paste is ambiguous - no earlier text may masquerade as its intent")
    assert "<image name=" not in prompts[0]
    print("PASS: a silent paste gets a plain describe prompt, no borrowed hint")


def test_injected_context_never_becomes_a_hint():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"input": [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /home/u\n- always do X"}]},
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "<environment_context>\n<cwd>/home/u</cwd>\n</environment_context>"}]},
        {"type": "message", "role": "user",
         "content": [
             {"type": "input_text", "text": '<image name=[Image #1] path="/tmp/codex-clipboard-x.png">'},
             {"type": "input_image", "image_url": "data:image/png;base64,AAA"},
             {"type": "input_text", "text": "</image>"},
         ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "AGENTS.md" not in prompts[0] and "environment_context" not in prompts[0], prompts[0]
    assert "know which details matter most" not in prompts[0], "with no real user text the hint block must be omitted"
    print("PASS: injected instruction blocks never masquerade as the user's request")


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
    test_prompt_always_asks_for_full_description()
    test_hint_is_truncated_keeping_the_tail()
    test_view_image_uses_assistant_intent()
    test_new_user_turn_resets_assistant_intent()
    test_silent_paste_gets_no_hint()
    test_injected_context_never_becomes_a_hint()
    test_cache_is_per_prompt()
    test_rewrite_prefix_is_stable()
