#!/usr/bin/env python3
"""Unit test: vision failures degrade to a visible note instead of failing the request.

A failed vision call (invalid key, network outage, upstream 5xx/429) used to
raise VisionError and make the proxy answer the whole request -- including its
plain-text parts -- with 502, blocking the conversation. By design, failed
images are now replaced by a "[vision unavailable: <reason>]" note so the text
parts of the conversation can continue while the vision side is broken. The
failure is never silent: the reason travels with the note and the proxy logs it.
"""

import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PNG = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}


def _load_proxy():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "vision_proxy.py")
    spec = importlib.util.spec_from_file_location("ds_proxy_fail_open_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _responses_body(image_url):
    return {"model": "user-configured-model", "input": [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "check this"},
                     {"type": "input_image", "image_url": image_url}]},
    ]}


def test_vision_failure_degrades_by_default():
    mod = _load_proxy()

    def boom(_url, _prompt=None):
        raise mod.VisionError("Vision API HTTP 401: unauthorized")

    mod._image_desc_from_url = boom
    body = _responses_body("data:image/png;base64,AAA")
    assert asyncio.run(mod._rewrite_image_inputs(body))

    content = body["input"][0]["content"]
    assert any(block.get("text", "").startswith("[vision proxy]") for block in content), content
    assert content[-1]["type"] == "input_text", content
    text = content[-1]["text"]
    assert text.startswith("[vision unavailable: "), text
    assert "unauthorized" in text, text
    assert "temporarily unavailable" in text, text
    assert "[vision model description]" not in text, \
        "an unavailable note is not a model description and must not wear its prefix"
    print("PASS: a failed vision call degrades to a visible note by default")


def test_mixed_success_and_failure():
    mod = _load_proxy()

    def flaky(url, _prompt=None):
        if "GOOD" in url:
            return "GOOD-DESC"
        raise mod.VisionError("vision timeout")

    mod._image_desc_from_url = flaky
    body = {"model": "user-configured-model", "input": [
        {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": "compare"},
                     {"type": "input_image", "image_url": "data:image/png;base64,GOOD"},
                     {"type": "input_image", "image_url": "data:image/png;base64,BAD"}]},
    ]}
    assert asyncio.run(mod._rewrite_image_inputs(body))

    texts = [c["text"] for c in body["input"][0]["content"]]
    assert "[vision model description] GOOD-DESC" in texts, texts
    assert any(t.startswith("[vision unavailable: ") and "timeout" in t for t in texts), texts
    print("PASS: successes are described and failures degrade independently")


def test_anthropic_dialect():
    mod = _load_proxy()

    def boom(_url, _prompt=None):
        raise mod.VisionError("Vision API network error: connection refused")

    mod._image_desc_from_url = boom
    body = {"messages": [{"role": "user", "content": [dict(PNG)]}]}
    assert asyncio.run(mod._rewrite_image_inputs(body))

    content = body["messages"][0]["content"]
    assert content[0]["text"].startswith("[vision proxy]"), content
    assert content[-1]["type"] == "text", content
    text = content[-1]["text"]
    assert text.startswith("[vision unavailable: "), text
    assert "connection refused" in text, text
    print("PASS: Anthropic-dialect failures degrade too")


if __name__ == "__main__":
    test_vision_failure_degrades_by_default()
    test_mixed_success_and_failure()
    test_anthropic_dialect()
