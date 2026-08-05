#!/usr/bin/env python3
"""Shared OpenAI-compatible vision client used by the proxy and glance CLI."""

from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

DEFAULT_PROMPT = "Please describe the contents of this image in detail."

LANG_INSTRUCTIONS = {
    "zh": "请使用简体中文回答。",
    "en": "Please respond in English.",
}


class VisionError(RuntimeError):
    """A safe, user-facing vision request failure."""


def load_env_file(path: str | os.PathLike[str] | None) -> None:
    if not path:
        return
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # The env file is the user's explicit configuration: whatever it sets wins,
        # even when the same variable already exists in the system environment.
        if key:
            os.environ[key] = value


def load_default_env() -> None:
    explicit = os.environ.get("VISION_ENV_FILE")
    candidates = [Path(explicit).expanduser()] if explicit else []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "agent-vision-toolkit" / "env")
    candidates.extend([
        Path.home() / ".config" / "agent-vision-toolkit" / "env",
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / ".env",
    ])
    for path in candidates:
        load_env_file(path)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise VisionError(f"Missing config {name}; fill it in the .env file")
    return value


def validate_vision_config() -> None:
    for name in ("VISION_API_KEY", "VISION_BASE_URL", "VISION_MODEL"):
        _required(name)


def image_path_to_data_url(path: str | os.PathLike[str]) -> str:
    image_path = Path(path).expanduser()
    if not image_path.is_file():
        raise VisionError(f"Image not found: {image_path}")
    mime, _ = mimetypes.guess_type(image_path.name)
    if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        raise VisionError("Only PNG, JPEG, GIF, and WebP images are supported")
    return f"data:{mime};base64,{base64.b64encode(image_path.read_bytes()).decode()}"


def _message_text(message: object) -> str:
    if isinstance(message, str):
        return message.strip()
    if isinstance(message, list):
        return "\n".join(
            part["text"] for part in message
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
    return ""


def describe_image(image_url: str | list[str], prompt: str | None = None, max_tokens: int = 4096,
                   apply_lang: bool = True) -> str:
    """Describe one data/http image URL (str) or several (list) in a single call."""
    validate_vision_config()
    urls = [image_url] if isinstance(image_url, str) else list(image_url)
    if not urls:
        raise VisionError("No image was provided")
    for url in urls:
        if not url.startswith(("data:", "http://", "https://")):
            raise VisionError("Only data URLs or http(s) image URLs are supported")
    base_url = _required("VISION_BASE_URL").rstrip("/")
    api_key = _required("VISION_API_KEY")
    text = prompt or DEFAULT_PROMPT
    if apply_lang:
        instruction = LANG_INSTRUCTIONS.get(os.environ.get("LANG", "").strip().lower())
        if instruction:
            text = f"{instruction}\n\n{text}"
    payload = {
        "model": _required("VISION_MODEL"),
        "messages": [{"role": "user", "content": [{"type": "text", "text": text}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in urls
        ]}],
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    retries = 2
    timeout = 180
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.load(response)
            try:
                text = _message_text(data["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError) as exc:
                raise VisionError("Vision API returned an incompatible response structure") from exc
            if not text:
                raise VisionError("Vision API returned an empty description")
            return text
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:400].replace(api_key, "<redacted>")
            body = body.replace("\r", " ").replace("\n", " ")
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                print(f"vision: HTTP {exc.code}, retrying ({attempt + 1}/{retries})", file=sys.stderr)
                time.sleep(min(2 ** attempt, 4))
                continue
            raise VisionError(f"Vision API HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt < retries:
                print(f"vision: {type(exc).__name__}, retrying ({attempt + 1}/{retries})", file=sys.stderr)
                time.sleep(min(2 ** attempt, 4))
                continue
            reason = getattr(exc, "reason", str(exc))
            raise VisionError(f"Vision API network error: {reason}") from exc
        except json.JSONDecodeError as exc:
            raise VisionError("Vision API returned invalid JSON") from exc
    raise VisionError("Vision API request failed")
