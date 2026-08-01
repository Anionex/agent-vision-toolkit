#!/usr/bin/env python3
"""Verify the proxy's image -> text rewrite chain end to end.

Usage: test_view_image_chain.py [--proxy URL] [--model SLUG] <image-path>

Sends a request with an input_image (data URL) through the proxy and asserts
that the DeepSeek reply describes the image instead of answering
"I'm unable to see the image".

API key resolution: --key-cmd output, else $DEEPSEEK_API_KEY, else the
DEEPSEEK_API_KEY line in .env (current dir or --env-file).
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

PROMPT = "请详细描述这张图片的内容"


def extract_text(raw):
    """Extract final text from either JSON or SSE Responses output."""
    objects = []
    try:
        objects.append(json.loads(raw))
    except json.JSONDecodeError:
        for line in raw.splitlines():
            if line.startswith("data:"):
                try:
                    objects.append(json.loads(line[5:].strip()))
                except json.JSONDecodeError:
                    pass

    texts = []
    def visit(value):
        if isinstance(value, dict):
            if value.get("type") in {"output_text", "response.output_text.done"} and isinstance(value.get("text"), str):
                texts.append(value["text"])
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for obj in objects:
        visit(obj)
    return "\n".join(dict.fromkeys(text for text in texts if text.strip())).strip()


def load_env_file(path):
    if not path or not os.path.isfile(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_key(key_cmd):
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    if key_cmd:
        return subprocess.run(key_cmd, shell=True, capture_output=True,
                              text=True).stdout.strip()
    raise SystemExit("no API key: set DEEPSEEK_API_KEY or pass --key-cmd")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", default="http://127.0.0.1:19100/responses")
    ap.add_argument("--model", default=os.environ.get("MODEL_SLUG", "deepseek-v4-flash-vision"))
    ap.add_argument("--key-cmd", default=None,
                    help="shell command printing the DeepSeek API key")
    ap.add_argument("--env-file", default=None,
                    help=".env file to load DEEPSEEK_API_KEY from (default: ./.env)")
    ap.add_argument("image")
    args = ap.parse_args()

    load_env_file(args.env_file or ".env")
    img = args.image
    b64 = base64.b64encode(open(img, "rb").read()).decode()
    body = {
        "model": args.model,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": PROMPT},
            {"type": "input_image", "image_url": "data:image/png;base64," + b64},
        ]}],
        "reasoning": {"effort": "none"},
        "store": False,
        "stream": False,
        "text": {"format": {"type": "text"}},
    }
    req = urllib.request.Request(
        args.proxy, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + get_key(args.key_cmd)},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=180)
        data = resp.read().decode()
    except urllib.error.HTTPError as e:
        print("HTTP ERROR:", e.code)
        print(e.read().decode()[:500])
        sys.exit(1)

    answer = extract_text(data)
    if not answer:
        print("FAIL: no output text found")
        print(data[:500])
        sys.exit(1)
    print("deepseek answer:", answer[:300])
    if "unable to see the image" in answer.lower() or "unsupported" in answer.lower():
        print("FAIL: image was NOT replaced by a text description")
        sys.exit(1)
    print("PASS: image was described via the vision rewrite chain")
    sys.exit(0)


if __name__ == "__main__":
    main()
