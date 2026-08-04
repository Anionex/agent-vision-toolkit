#!/usr/bin/env python3
"""Unit test: Anthropic Messages requests (Claude Code) are rewritten too.

Images reach an Anthropic-dialect proxy in two shapes:
  A) user message content        [{type: image, source: {...}}]   (pasted images)
  B) tool_result inner content   [{type: image, source: {...}}]   (Read on an image file)

The focus-hint policy is the same as for Codex: a pasted image rides only its
own message's text, a tool-fetched image rides the assistant's stated reason
for looking (thinking or message text), and injected blocks never become hints.
"""

import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PNG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "codex-vision-proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_anthropic_mod", path)
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


def test_pasted_image_is_rewritten_with_same_message_hint():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"model": "user-configured-model", "messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "why does the login page look broken [Image #1]"},
            dict(PNG),
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    content = body["messages"][0]["content"]
    assert content[1]["type"] == "text" and content[1]["text"].startswith("[vision proxy]"), content
    assert content[2] == {"type": "text", "text": "[vision model description] DESC"}, content
    assert "login page look broken" in prompts[0], prompts[0]
    assert "Do not answer the user's request yourself" in prompts[0]
    print("PASS: pasted image blocks are rewritten and ride their own message's text")


def test_tool_result_image_rides_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "user", "content": [{"type": "text", "text": "修复登录页样式"}]},
        {"role": "assistant", "content": [
            {"type": "text", "text": "我看一下失败截图确认按钮颜色"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a.png"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [dict(PNG)]},
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    inner = body["messages"][2]["content"][0]["content"]
    assert inner[-1] == {"type": "text", "text": "[vision model description] DESC"}, inner
    assert "确认按钮颜色" in prompts[0], prompts[0]
    assert "decided to view" in prompts[0]
    assert "修复登录页样式" not in prompts[0], "assistant intent replaces, not augments, the user text"
    print("PASS: tool_result images ride the assistant's stated intent")


def test_thinking_is_an_intent_source():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "user", "content": [{"type": "text", "text": "修复登录页样式"}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "翻了一遍日志没有线索。\n\n先看失败截图确认按钮颜色。", "signature": "s"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a.png"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [dict(PNG)]},
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "确认按钮颜色" in prompts[0], prompts[0]
    assert "翻了一遍日志" not in prompts[0], "only the closing paragraph of the thinking is the hint"
    assert "decided to view" in prompts[0]
    print("PASS: thinking blocks count as assistant intent, closing paragraph only")


def test_tool_result_does_not_reset_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "assistant", "content": [
            {"type": "text", "text": "对比一下两张截图的配色"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a.png"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [
                {"type": "text", "text": "read 1 image"}]},
            {"type": "system-reminder-like", "text": "noise"},
        ]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/tmp/b.png"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": [dict(PNG)]},
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "配色" in prompts[0], (
        "a tool_result-only user message is not a user turn and must not clear assistant intent")
    print("PASS: tool_result-only user messages keep assistant intent alive")


def test_new_user_turn_resets_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "assistant", "content": [{"type": "text", "text": "上一轮的旧意图"}]},
        {"role": "user", "content": "看看这个图表的趋势"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/tmp/a.png"}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [dict(PNG)]},
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "图表的趋势" in prompts[0], prompts[0]
    assert "旧意图" not in prompts[0], "intent from before the latest user turn is stale"
    print("PASS: a new user turn (string content) invalidates earlier assistant intent")


def test_injected_blocks_never_become_hints():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "<system-reminder>\nAs you answer, remember X.\n</system-reminder>"},
            {"type": "text", "text": "[Image #1]"},
            dict(PNG),
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "remember X" not in prompts[0], prompts[0]
    assert "know which details matter most" not in prompts[0], (
        "with no real user text the hint block must be omitted")
    print("PASS: system reminders and image placeholders never masquerade as the request")


def test_url_source_is_supported():
    mod = _load_proxy()
    urls = []

    def fake(url, prompt=None):
        urls.append(url)
        return "DESC"

    mod._image_desc_from_url = fake
    body = {"messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "look"},
            {"type": "image", "source": {"type": "url", "url": "https://example.com/a.png"}},
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert urls == ["https://example.com/a.png"], urls
    print("PASS: url image sources pass through as-is")


def test_base64_source_becomes_data_url():
    mod = _load_proxy()
    urls = []

    def fake(url, prompt=None):
        urls.append(url)
        return "DESC"

    mod._image_desc_from_url = fake
    body = {"messages": [
        {"role": "user", "content": [dict(PNG)]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert urls == ["data:image/png;base64,AAAA"], urls
    print("PASS: base64 sources are wrapped into data URLs for the vision client")


def test_channel_note_mentions_reading_not_view_image():
    mod = _load_proxy()
    _capture(mod)
    body = {"messages": [{"role": "user", "content": [dict(PNG)]}]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    note = body["messages"][0]["content"][0]["text"]
    assert note.startswith("[vision proxy]"), note
    assert "view_image" not in note, "the Codex tool name would be a dead reference in Claude Code"
    print("PASS: the anthropic channel note does not name Codex's view_image tool")


def test_failure_is_not_forwarded():
    mod = _load_proxy()
    mod._image_desc_from_url = lambda _url, _prompt=None: None
    body = {"messages": [{"role": "user", "content": [dict(PNG)]}]}
    try:
        asyncio.run(mod._rewrite_image_inputs(body))
    except mod.VisionError:
        pass
    else:
        raise AssertionError("failed vision calls must raise instead of forwarding the image")
    assert body["messages"][0]["content"][0]["type"] == "image"
    print("PASS: a failed description still fails closed in the anthropic dialect")


def test_text_only_anthropic_body_is_untouched():
    mod = _load_proxy()
    _capture(mod)
    body = {"messages": [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "ok"}]},
        ]},
    ]}
    assert not asyncio.run(mod._rewrite_image_inputs(body))
    print("PASS: text-only anthropic bodies pass through unchanged")


if __name__ == "__main__":
    test_pasted_image_is_rewritten_with_same_message_hint()
    test_tool_result_image_rides_assistant_intent()
    test_thinking_is_an_intent_source()
    test_tool_result_does_not_reset_assistant_intent()
    test_new_user_turn_resets_assistant_intent()
    test_injected_blocks_never_become_hints()
    test_url_source_is_supported()
    test_base64_source_becomes_data_url()
    test_channel_note_mentions_reading_not_view_image()
    test_failure_is_not_forwarded()
    test_text_only_anthropic_body_is_untouched()
