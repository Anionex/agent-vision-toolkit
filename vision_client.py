#!/usr/bin/env python3
"""Shared OpenAI-compatible vision client used by the proxy and glance CLI."""

from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import os
from pathlib import Path
import time
import urllib.error
import urllib.request

DEFAULT_PROMPT = "请详细描述这张图片中的内容。"


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
        if key and key not in os.environ:
            os.environ[key] = value


def load_default_env() -> None:
    explicit = os.environ.get("CODEX_DEEPSEEK_VISION_ENV")
    candidates = [Path(explicit).expanduser()] if explicit else []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "codex-deepseek-vision" / "env")
    candidates.extend([
        Path.home() / ".config" / "codex-deepseek-vision" / "env",
        Path(__file__).resolve().parent / ".env",
        Path.cwd() / ".env",
    ])
    for path in candidates:
        load_env_file(path)


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise VisionError(f"缺少配置 {name}；请在 .env 中填写")
    return value


def validate_vision_config() -> None:
    for name in ("VISION_API_KEY", "VISION_BASE_URL", "VISION_MODEL"):
        _required(name)


def image_path_to_data_url(path: str | os.PathLike[str]) -> str:
    image_path = Path(path).expanduser()
    if not image_path.is_file():
        raise VisionError(f"图片不存在: {image_path}")
    mime, _ = mimetypes.guess_type(image_path.name)
    if mime not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
        raise VisionError("只支持 PNG、JPEG、GIF 和 WebP 图片")
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


def describe_image(image_url: str, prompt: str | None = None, max_tokens: int | None = None) -> str:
    """Describe a data/http image URL through an OpenAI-compatible endpoint."""
    validate_vision_config()
    if not image_url.startswith(("data:", "http://", "https://")):
        raise VisionError("只支持 data URL 或 http(s) 图片 URL")
    base_url = _required("VISION_BASE_URL").rstrip("/")
    api_key = _required("VISION_API_KEY")
    payload = {
        "model": _required("VISION_MODEL"),
        "max_tokens": max_tokens or 4096,
        "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt or DEFAULT_PROMPT},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]}],
    }
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
                raise VisionError("视觉 API 返回了不兼容的响应结构") from exc
            if not text:
                raise VisionError("视觉 API 返回了空描述")
            return text
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")[:400].replace(api_key, "<redacted>")
            body = body.replace("\r", " ").replace("\n", " ")
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(min(2 ** attempt, 4))
                continue
            raise VisionError(f"视觉 API HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if attempt < retries:
                time.sleep(min(2 ** attempt, 4))
                continue
            reason = getattr(exc, "reason", str(exc))
            raise VisionError(f"视觉 API 网络错误: {reason}") from exc
        except json.JSONDecodeError as exc:
            raise VisionError("视觉 API 返回了无效 JSON") from exc
    raise VisionError("视觉 API 请求失败")
