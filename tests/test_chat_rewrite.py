#!/usr/bin/env python3
"""Unit test: OpenAI Chat Completions requests (Cline, Roo, Aider, ...) are rewritten.

Chat-Completions hosts attach images as {type: image_url} blocks inside
messages[].content. The focus-hint policy is shared with the other dialects:
a user-attached image rides only its own message's text, a tool-returned image
rides the assistant's last stated reason, and host-injected environment blocks
never become hints.
"""

import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IMG = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "codex-vision-proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_chat_mod", path)
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


def test_user_image_is_rewritten_with_same_message_hint():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"model": "user-configured-model", "messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "why does the login page look broken"},
            dict(IMG),
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    content = body["messages"][0]["content"]
    assert content[1]["type"] == "text" and content[1]["text"].startswith("[vision proxy]"), content
    assert content[2] == {"type": "text", "text": "[vision model description] DESC"}, content
    assert "login page look broken" in prompts[0], prompts[0]
    print("PASS: image_url blocks are rewritten and ride their own message's text")


def test_environment_details_never_become_hints():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "<environment_details>\ncwd: /home/u\n</environment_details>"},
            dict(IMG),
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "cwd" not in prompts[0], prompts[0]
    assert "know which details matter most" not in prompts[0], (
        "with no real user text the hint block must be omitted")
    print("PASS: injected environment blocks never masquerade as the request")


def test_tool_message_image_rides_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "user", "content": "修复登录页样式"},
        {"role": "assistant", "content": "我看一下失败截图确认按钮颜色",
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "screenshot", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": [dict(IMG)]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "确认按钮颜色" in prompts[0], prompts[0]
    assert "decided to view" in prompts[0]
    assert "修复登录页样式" not in prompts[0], "assistant intent replaces, not augments, the user text"
    print("PASS: tool-returned images ride the assistant's stated intent")


def test_string_image_url_variant_is_supported():
    mod = _load_proxy()
    urls = []

    def fake(url, prompt=None):
        urls.append(url)
        return "DESC"

    mod._image_desc_from_url = fake
    body = {"messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "look"},
            {"type": "image_url", "image_url": "https://example.com/a.png"},
        ]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert urls == ["https://example.com/a.png"], urls
    print("PASS: the bare-string image_url variant is accepted")


def test_new_user_turn_resets_assistant_intent():
    mod = _load_proxy()
    prompts = _capture(mod)
    body = {"messages": [
        {"role": "assistant", "content": "上一轮的旧意图"},
        {"role": "user", "content": "看看这个图表的趋势"},
        {"role": "tool", "tool_call_id": "t1", "content": [dict(IMG)]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    assert "图表的趋势" in prompts[0], prompts[0]
    assert "旧意图" not in prompts[0], "intent from before the latest user turn is stale"
    print("PASS: a new user turn invalidates earlier assistant intent")


def test_channel_note_is_generic():
    mod = _load_proxy()
    _capture(mod)
    body = {"messages": [{"role": "user", "content": [dict(IMG)]}]}
    assert asyncio.run(mod._rewrite_image_inputs(body))
    note = body["messages"][0]["content"][0]["text"]
    assert note.startswith("[vision proxy]"), note
    assert "view_image" not in note, "no Chat-Completions host has Codex's view_image tool"
    print("PASS: the chat channel note names no host-specific tool")


def test_failure_is_not_forwarded():
    mod = _load_proxy()
    mod._image_desc_from_url = lambda _url, _prompt=None: None
    body = {"messages": [{"role": "user", "content": [dict(IMG)]}]}
    try:
        asyncio.run(mod._rewrite_image_inputs(body))
    except mod.VisionError:
        pass
    else:
        raise AssertionError("failed vision calls must raise instead of forwarding the image")
    assert body["messages"][0]["content"][0]["type"] == "image_url"
    print("PASS: a failed description still fails closed in the chat dialect")


def test_text_only_chat_body_is_untouched():
    mod = _load_proxy()
    _capture(mod)
    body = {"messages": [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]}
    assert not asyncio.run(mod._rewrite_image_inputs(body))
    print("PASS: text-only chat bodies pass through unchanged")


if __name__ == "__main__":
    test_user_image_is_rewritten_with_same_message_hint()
    test_environment_details_never_become_hints()
    test_tool_message_image_rides_assistant_intent()
    test_string_image_url_variant_is_supported()
    test_new_user_turn_resets_assistant_intent()
    test_channel_note_is_generic()
    test_failure_is_not_forwarded()
    test_text_only_chat_body_is_untouched()
