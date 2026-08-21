#!/usr/bin/env python3
"""Shared multi-provider vision client used by the proxy and glance CLI."""

from __future__ import annotations

import base64
from email.utils import parsedate_to_datetime
import gzip
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
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

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
    if explicit:
        load_env_file(Path(explicit).expanduser())
        return
    candidates = []
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


def _responses_text(response: object) -> str:
    if not isinstance(response, dict) or not isinstance(response.get("output"), list):
        return ""
    return "\n".join(
        part["text"]
        for item in response["output"]
        if isinstance(item, dict) and item.get("type") == "message"
        and isinstance(item.get("content"), list)
        for part in item["content"]
        if isinstance(part, dict) and part.get("type") == "output_text"
        and isinstance(part.get("text"), str)
    ).strip()


def _anthropic_image_source(url: str) -> dict[str, str]:
    if not url.startswith("data:"):
        return {"type": "url", "url": url}
    header, separator, data = url.partition(",")
    if separator == "" or ";base64" not in header:
        raise VisionError("Anthropic image data URLs must use base64 encoding")
    media_type = header[5:].split(";", 1)[0]
    if not media_type:
        raise VisionError("Anthropic image data URLs must include a media type")
    return {"type": "base64", "media_type": media_type, "data": data}


def _anthropic_text(response: object) -> str:
    if not isinstance(response, dict) or not isinstance(response.get("content"), list):
        return ""
    return "\n".join(
        block["text"]
        for block in response["content"]
        if isinstance(block, dict) and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ).strip()


def _redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def _retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    value = error.headers.get("Retry-After")
    if value:
        try:
            return max(0.0, min(float(value), 60.0))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
                return max(0.0, min(retry_at.timestamp() - time.time(), 60.0))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(2 ** attempt, 4)


def _api_error_code(body: bytes) -> str:
    try:
        payload = json.loads(body.decode(errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    code = error.get("code")
    return code if isinstance(code, str) else ""


def _decompress_body(raw: bytes, response) -> bytes:
    """Decompress a response body when the server advertises gzip encoding.

    urllib does not transparently decompress gzip responses; the bundled
    http.client leaves the raw compressed bytes untouched.
    """
    encoding = (response.headers.get("Content-Encoding") or "").lower()
    if encoding == "gzip" and raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def _retryable_http_error(status: int, body: bytes) -> bool:
    if status not in {429, 500, 502, 503, 504, 529}:
        return False
    return _api_error_code(body) not in {
        "daily_rate_limit_exceeded",
        "global_daily_limit_exceeded",
    }


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
    user_agent = os.environ.get("VISION_USER_AGENT", "").strip() or DEFAULT_USER_AGENT
    text = prompt or DEFAULT_PROMPT
    if apply_lang:
        instruction = LANG_INSTRUCTIONS.get(os.environ.get("LANG", "").strip().lower())
        if instruction:
            text = f"{instruction}\n\n{text}"
    model = _required("VISION_MODEL")
    protocol = os.environ.get("VISION_API_PROTOCOL", "").strip().lower() or "chat_completions"
    if protocol == "responses":
        payload = {
            "model": model,
            "store": False,
            "input": [{"role": "user", "content": [
                {"type": "input_image", "image_url": url} for url in urls
            ] + [{"type": "input_text", "text": text}]}],
        }
        if max_tokens is not None:
            payload["max_output_tokens"] = max_tokens
        reasoning_effort = os.environ.get("VISION_REASONING_EFFORT", "").strip()
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        endpoint = "/responses"
        extract_text = _responses_text
    elif protocol == "chat_completions":
        payload = {
            "model": model,
            "stream": False,
            "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": url}} for url in urls
            ] + [{"type": "text", "text": text}]}],
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        endpoint = "/chat/completions"
        extract_text = lambda data: _message_text(data["choices"][0]["message"]["content"])
    elif protocol == "anthropic":
        payload = {
            "model": model,
            "max_tokens": max_tokens if max_tokens is not None else 4096,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": _anthropic_image_source(url)} for url in urls
            ] + [{"type": "text", "text": text}]}],
        }
        thinking = os.environ.get("VISION_ANTHROPIC_THINKING", "").strip().lower() or "omit"
        if thinking != "omit":
            if thinking not in {"disabled", "adaptive"}:
                raise VisionError(
                    "Unsupported VISION_ANTHROPIC_THINKING; use omit, disabled, or adaptive"
                )
            payload["thinking"] = {"type": thinking}
        endpoint = "/messages"
        extract_text = _anthropic_text
    else:
        raise VisionError(
            "Unsupported VISION_API_PROTOCOL; use chat_completions, responses, or anthropic"
        )
    headers = {
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    if protocol == "anthropic":
        headers.update({
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        })
    else:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(base_url + endpoint, data=json.dumps(payload).encode(), headers=headers)
    retries = 2
    timeout = 180
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                data = json.loads(_decompress_body(raw, response))
            try:
                text = extract_text(data)
            except (KeyError, IndexError, TypeError) as exc:
                raise VisionError("Vision API returned an incompatible response structure") from exc
            if not text:
                raise VisionError("Vision API returned an empty description")
            return text
        except urllib.error.HTTPError as exc:
            raw_body = _decompress_body(exc.read(), exc)
            body = _redact(raw_body.decode(errors="replace")[:400], api_key)
            body = body.replace("\r", " ").replace("\n", " ")
            if _retryable_http_error(exc.code, raw_body) and attempt < retries:
                print(f"vision: HTTP {exc.code}, retrying ({attempt + 1}/{retries})", file=sys.stderr)
                time.sleep(_retry_delay(exc, attempt))
                continue
            raise VisionError(f"Vision API HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt < retries:
                print(f"vision: {type(exc).__name__}, retrying ({attempt + 1}/{retries})", file=sys.stderr)
                time.sleep(min(2 ** attempt, 4))
                continue
            reason = _redact(str(getattr(exc, "reason", str(exc))), api_key)
            raise VisionError(f"Vision API network error: {reason}") from exc
        except json.JSONDecodeError as exc:
            raise VisionError("Vision API returned invalid JSON") from exc
    raise VisionError("Vision API request failed")
