#!/usr/bin/env python3
"""Safely split a tall screenshot, OCR each chunk with glance, and merge it."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata
from typing import Sequence

try:
    from PIL import Image, ImageChops, ImageOps
except ImportError:  # Optional dependency; handled by main().
    Image = None
    ImageChops = None
    ImageOps = None


ANALYSIS_WIDTH = 900
SAFE_OCCUPANCY_LEVEL = 20.0
# Bump when the OCR output contract changes so --resume cannot reuse stale results.
OCR_PROMPT_VERSION = 2


@dataclass(frozen=True)
class CoreRange:
    top: int
    bottom: int
    cut_energy: float | None
    cut_quality: float | None
    top_safe_margin: int | None
    bottom_safe_margin: int | None


@dataclass(frozen=True)
class Chunk:
    index: int
    core_top: int
    core_bottom: int
    crop_top: int
    crop_bottom: int
    top_overlap: int
    bottom_overlap: int
    cut_energy: float | None
    cut_quality: float | None
    top_safe_margin: int | None
    bottom_safe_margin: int | None
    image_path: Path
    image_sha256: str


@dataclass(frozen=True)
class ChatMessage:
    speaker: str
    content: str
    timestamp: str = ""
    message_type: str = "message"
    quoted_speaker: str = ""
    quoted_content: str = ""


@dataclass(frozen=True)
class Transcript:
    chunk: Chunk
    text: str
    output_path: Path
    reused: bool
    messages: tuple[ChatMessage, ...] = ()


def clamp(value: float, minimum: int, maximum: int) -> int:
    return round(max(minimum, min(maximum, value)))


def percentile(values: Sequence[float], percent: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] * (1 - fraction) + ordered[upper] * fraction)


def rolling_mean(values: Sequence[float], radius: int) -> list[float]:
    if radius <= 0 or len(values) <= 1:
        return [float(value) for value in values]
    padded = [float(values[0])] * radius
    padded.extend(float(value) for value in values)
    padded.extend([float(values[-1])] * radius)
    window = radius * 2 + 1
    total = sum(padded[:window])
    result = []
    for index in range(len(values)):
        result.append(total / window)
        if index + window < len(padded):
            total += padded[index + window] - padded[index]
    return result


def row_energy(image: "Image.Image") -> tuple[list[float], list[float], float]:
    """Return per-row edge energy and foreground occupancy with Pillow operations."""
    scale = min(1.0, ANALYSIS_WIDTH / image.width)
    analysis_width = max(1, round(image.width * scale))
    analysis_height = max(1, round(image.height * scale))
    analysis = image.convert("RGB")
    if scale < 1.0:
        analysis = analysis.resize(
            (analysis_width, analysis_height), Image.Resampling.BILINEAR
        )
    gray = analysis.convert("L")

    width, height = gray.size
    shifted_x = Image.new("L", gray.size)
    shifted_x.paste(gray, (1, 0))
    shifted_x.paste(gray.crop((0, 0, 1, height)), (0, 0))
    horizontal = ImageChops.difference(gray, shifted_x)

    shifted_y = Image.new("L", gray.size)
    shifted_y.paste(gray, (0, 1))
    shifted_y.paste(gray.crop((0, 0, width, 1)), (0, 0))
    vertical = ImageChops.difference(gray, shifted_y)

    combined = Image.blend(horizontal, vertical, 0.32)
    collapsed = combined.resize((1, height), Image.Resampling.BOX)
    edges = [float(value) for value in collapsed.tobytes()]

    border_width = max(1, min(24, width // 18))
    left = analysis.crop((0, 0, border_width, height)).resize(
        (1, height), Image.Resampling.BOX
    )
    right = analysis.crop((width - border_width, 0, width, height)).resize(
        (1, height), Image.Resampling.BOX
    )
    edge_reference = Image.new("RGB", (2, height))
    edge_reference.paste(left, (0, 0))
    edge_reference.paste(right, (1, 0))
    background = edge_reference.resize((width, height), Image.Resampling.BILINEAR)
    foreground_difference = ImageChops.difference(analysis, background)
    red_difference, green_difference, blue_difference = foreground_difference.split()
    foreground_distance = ImageChops.lighter(
        ImageChops.lighter(red_difference, green_difference), blue_difference
    )
    foreground_mask = foreground_distance.point(
        lambda value: 255 if value >= 14 else 0,
        mode="L",
    )
    occupancy_column = foreground_mask.resize((1, height), Image.Resampling.BOX)
    occupancy = [float(value) for value in occupancy_column.tobytes()]

    radius = max(1, round(3 * scale))
    smoothed_edges = rolling_mean(edges, radius)
    smoothed_occupancy = rolling_mean(occupancy, radius)
    energy = [
        edge_value + occupancy_value * 0.55
        for edge_value, occupancy_value in zip(smoothed_edges, smoothed_occupancy)
    ]
    return energy, smoothed_occupancy, scale


def resolve_split_sizes(
    width: int,
    mode: str,
    target_height: int | None,
    min_height: int | None,
    max_height: int | None,
    overlap: int | None,
) -> tuple[int, int, int, int]:
    automatic_target = clamp(
        width * (1.75 if mode == "chat" else 1.45),
        1400 if mode == "chat" else 1200,
        2400,
    )
    target = target_height or automatic_target
    minimum = min_height or max(600, round(target * 0.58))
    maximum = max_height or min(3400, round(target * 1.42))
    resolved_overlap = overlap if overlap is not None else (64 if mode == "chat" else 40)

    if min(target, minimum, maximum) <= 0:
        raise ValueError("split heights must be greater than zero")
    if not minimum <= target <= maximum:
        raise ValueError("split heights must satisfy min-height <= target-height <= max-height")
    if resolved_overlap < 0:
        raise ValueError("overlap cannot be negative")
    if resolved_overlap * 2 >= minimum:
        raise ValueError("overlap must be less than half of min-height")
    return target, minimum, maximum, resolved_overlap


def choose_cut(
    energy: Sequence[float],
    occupancy: Sequence[float],
    start: int,
    target: int,
    minimum: int,
    maximum: int,
    mode: str,
    safe_radius: int,
) -> tuple[int, float, float, int]:
    image_height = len(energy)
    lower = min(image_height - 1, start + minimum)
    upper = min(image_height - minimum, start + maximum)
    desired = min(image_height - 1, start + target)
    if lower >= upper:
        return upper, float(energy[upper]), 0.0, 0

    local = [float(value) for value in energy[lower : upper + 1]]
    low = percentile(local, 8)
    high = percentile(local, 92)
    normalized = [(value - low) / max(0.001, high - low) for value in local]

    threshold = percentile(local, 32 if mode == "chat" else 25)
    low_rows = [
        1.0
        if value <= threshold and occupancy[index] <= SAFE_OCCUPANCY_LEVEL
        else 0.0
        for index, value in enumerate(energy)
    ]
    blank_ratio = rolling_mean(low_rows, safe_radius)[lower : upper + 1]
    distance_weight = 0.20 if mode == "chat" else 0.30

    selected_offset = min(
        range(len(local)),
        key=lambda offset: (
            normalized[offset]
            + abs((lower + offset) - desired) / max(1, maximum - minimum) * distance_weight
            + occupancy[lower + offset] / 255 * 0.75
            - blank_ratio[offset] * 0.48
        ),
    )
    selected = lower + selected_offset

    band_threshold = percentile(local, 40)
    band_left = selected
    band_right = selected
    while (
        band_left > lower
        and energy[band_left - 1] <= band_threshold
        and occupancy[band_left - 1] <= SAFE_OCCUPANCY_LEVEL
    ):
        band_left -= 1
    while (
        band_right < upper
        and energy[band_right + 1] <= band_threshold
        and occupancy[band_right + 1] <= SAFE_OCCUPANCY_LEVEL
    ):
        band_right += 1
    if band_right - band_left >= max(4, safe_radius // 2):
        selected = (band_left + band_right) // 2
        safe_margin = min(selected - band_left, band_right - selected)
    else:
        safe_margin = 0

    selected_energy = float(energy[selected])
    percentile_rank = sum(value <= selected_energy for value in local) / len(local)
    quality = max(0.0, min(1.0, 1.0 - percentile_rank))
    return selected, selected_energy, quality, safe_margin


def find_core_ranges(
    image: "Image.Image",
    mode: str,
    target_height: int,
    min_height: int,
    max_height: int,
) -> tuple[list[CoreRange], dict[str, float]]:
    if image.height <= max_height:
        return [CoreRange(0, image.height, None, None, None, None)], {
            "analysis_scale": 1.0,
            "safe_band_radius_px": 0.0,
        }

    energy, occupancy, scale = row_energy(image)
    target = max(1, round(target_height * scale))
    minimum = max(1, round(min_height * scale))
    maximum = max(minimum + 1, round(max_height * scale))
    safe_radius = max(2, round(image.width * 0.012 * scale))

    cuts = [0]
    cut_details: list[tuple[float, float, int]] = []
    analysis_height = len(energy)
    while analysis_height - cuts[-1] > maximum:
        if analysis_height - cuts[-1] < minimum * 2:
            break
        cut, selected_energy, quality, safe_margin = choose_cut(
            energy,
            occupancy,
            cuts[-1],
            target,
            minimum,
            maximum,
            mode,
            safe_radius,
        )
        if cut <= cuts[-1]:
            cut = min(analysis_height, cuts[-1] + target)
        cuts.append(cut)
        cut_details.append((selected_energy, quality, safe_margin))
    cuts.append(analysis_height)

    original_cuts = [0]
    for cut in cuts[1:-1]:
        mapped = max(original_cuts[-1] + 1, min(image.height - 1, round(cut / scale)))
        original_cuts.append(mapped)
    original_cuts.append(image.height)

    ranges = []
    for index, (top, bottom) in enumerate(zip(original_cuts, original_cuts[1:])):
        detail = cut_details[index] if index < len(cut_details) else (None, None, None)
        top_safe_margin = (
            round(cut_details[index - 1][2] / scale) if index > 0 else None
        )
        bottom_safe_margin = (
            round(detail[2] / scale) if detail[2] is not None else None
        )
        ranges.append(
            CoreRange(
                top=top,
                bottom=bottom,
                cut_energy=detail[0],
                cut_quality=detail[1],
                top_safe_margin=top_safe_margin,
                bottom_safe_margin=bottom_safe_margin,
            )
        )
    return ranges, {
        "analysis_scale": scale,
        "safe_band_radius_px": safe_radius / scale,
    }


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def save_chunks(
    image: "Image.Image",
    ranges: Sequence[CoreRange],
    chunks_dir: Path,
    overlap: int,
) -> list[Chunk]:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks = []
    digits = max(3, len(str(len(ranges))))
    for index, core in enumerate(ranges, 1):
        top_overlap = (
            0
            if not core.top or (core.top_safe_margin is not None and core.top_safe_margin > 0)
            else overlap
        )
        bottom_overlap = (
            0
            if core.bottom >= image.height
            or (core.bottom_safe_margin is not None and core.bottom_safe_margin > 0)
            else overlap
        )
        crop_top = max(0, core.top - top_overlap)
        crop_bottom = min(image.height, core.bottom + bottom_overlap)
        image_path = chunks_dir / f"chunk_{index:0{digits}d}.png"

        buffer = io.BytesIO()
        image.crop((0, crop_top, image.width, crop_bottom)).save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
        image_sha256 = hashlib.sha256(image_bytes).hexdigest()
        existing_sha256 = (
            hashlib.sha256(image_path.read_bytes()).hexdigest()
            if image_path.is_file()
            else ""
        )
        if existing_sha256 != image_sha256:
            atomic_write_bytes(image_path, image_bytes)

        chunks.append(
            Chunk(
                index=index,
                core_top=core.top,
                core_bottom=core.bottom,
                crop_top=crop_top,
                crop_bottom=crop_bottom,
                top_overlap=top_overlap,
                bottom_overlap=bottom_overlap,
                cut_energy=core.cut_energy,
                cut_quality=core.cut_quality,
                top_safe_margin=core.top_safe_margin,
                bottom_safe_margin=core.bottom_safe_margin,
                image_path=image_path,
                image_sha256=image_sha256,
            )
        )
    prune_stale_chunk_files(chunks_dir, chunks)
    return chunks


def prune_stale_chunk_files(chunks_dir: Path, chunks: Sequence[Chunk]) -> None:
    active = set()
    for chunk in chunks:
        active.update(
            {
                chunk.image_path.name,
                chunk.image_path.with_suffix(".ocr.md").name,
                chunk.image_path.with_suffix(".ocr.md").name + ".sha256",
                chunk.image_path.with_suffix(".ocr.json").name,
                chunk.image_path.with_suffix(".ocr.json").name + ".sha256",
            }
        )
    generated = re.compile(
        r"chunk_\d+\.(?:png|ocr\.md(?:\.sha256)?|ocr\.json(?:\.sha256)?|ocr\.sha256)"
    )
    for path in chunks_dir.iterdir():
        if path.is_file() and generated.fullmatch(path.name) and path.name not in active:
            path.unlink()


def command_for_path(path: Path) -> list[str]:
    if path.suffix.lower() == ".py" or (os.name != "nt" and not os.access(path, os.X_OK)):
        return [sys.executable, str(path)]
    return [str(path)]


def resolve_glance_command() -> list[str]:
    discovered = shutil.which("glance")
    if discovered:
        return command_for_path(Path(discovered))
    repository_glance = Path(__file__).resolve().parents[3] / "bin" / "glance"
    if repository_glance.is_file():
        return command_for_path(repository_glance)
    raise FileNotFoundError("glance is not on PATH; install the toolkit first")


def ocr_prompt(mode: str, index: int, total: int, custom: str | None) -> str:
    if mode == "chat":
        instructions = (
            "Transcribe this chat screenshot chunk in strict top-to-bottom message order. "
            "Return only one valid JSON object with this exact shape: "
            '{"messages":[{"speaker":"visible name","content":"message text",'
            '"timestamp":"","message_type":"message","quoted_speaker":"",'
            '"quoted_content":""}]}. '
            "Give every message a speaker and copy the visible nickname exactly; never replace "
            "it with roles such as customer, support, me, or other. If the screenshot shows a "
            "question-mark square glyph in a nickname, preserve it as Unicode U+25A1. Merge "
            "screen-width wrapping back into the same message. Each rounded message bubble is "
            "exactly one message: keep code blocks, bullet lists, attachment filenames, and file "
            "metadata inside that bubble's content instead of creating a second message. Preserve "
            "intentional code and list line breaks. Put replied-to text in "
            "quoted_speaker and quoted_content while keeping the new message in speaker and "
            "content. Fill timestamp only when the entire timestamp is clearly visible; "
            "otherwise leave it empty. message_type must be message, system, image, or file. "
            "Do not summarize, rewrite, translate, or infer clipped text. Use [unreadable] for "
            "visible text that cannot be read and [clipped] for a visibly cut-off message."
        )
    else:
        instructions = (
            "Keep the visible top-to-bottom reading order and preserve wording, punctuation, "
            "line breaks, labels, timestamps, headings, lists, tables, code, quoted text, and "
            "paragraph order. Do not infer clipped or hidden content; write [unreadable] only "
            "where visible text cannot be read."
        )
    chunk_note = f" This is chunk {index} of {total} from one vertically scrolling screenshot."
    custom_note = f" {custom.strip()}" if custom and custom.strip() else ""
    return instructions + chunk_note + custom_note


def join_visual_wraps(content: str) -> str:
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not content:
        return ""
    paragraphs = re.split(r"\n\s*\n", content)
    normalized = []
    list_pattern = re.compile(r"^(?:[-*+\u2022] |\d+[.)] )")
    code_line_pattern = re.compile(r"^[A-Za-z0-9_.-]+:\s+\S")
    for paragraph in paragraphs:
        lines = [re.sub(r"[ \t]+", " ", line.strip()) for line in paragraph.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            continue
        merged = lines[0]
        for line in lines[1:]:
            if list_pattern.match(line) or code_line_pattern.match(line):
                merged += "\n" + line
                continue
            separator = (
                " "
                if re.search(r"[A-Za-z0-9]$", merged) and re.match(r"[A-Za-z0-9]", line)
                else ""
            )
            merged += separator + line
        normalized.append(merged)
    return "\n\n".join(normalized)


def normalize_timestamp(value: object) -> str:
    timestamp = str(value or "").strip()
    lowered = timestamp.casefold()
    if any(marker in lowered for marker in ("[unreadable]", "[clipped]")):
        return ""
    if re.search(r"[:\uFF1A]\d$", timestamp):
        return ""
    return timestamp


def parse_chat_messages(raw_text: str) -> tuple[ChatMessage, ...]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    if start < 0:
        raise ValueError("chat OCR did not return a JSON object")
    try:
        payload, _end = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValueError(f"chat OCR returned invalid JSON: {exc.msg}") from exc
    records = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise ValueError("chat OCR JSON is missing a messages array")

    messages = []
    for record in records:
        if not isinstance(record, dict):
            continue
        content = join_visual_wraps(str(record.get("content") or ""))
        if not content:
            continue
        message_type = str(record.get("message_type") or "message").strip().lower()
        if message_type not in {"message", "system", "image", "file"}:
            message_type = "message"
        speaker = str(record.get("speaker") or "").strip()
        speaker = re.sub(r"\u25a1\s+\u3002", "\u25a1\u3002", speaker)
        if message_type == "system":
            speaker = "system"
        if not speaker:
            speaker = "[unreadable speaker]"
        messages.append(
            ChatMessage(
                speaker=speaker,
                content=content,
                timestamp=normalize_timestamp(record.get("timestamp")),
                message_type=message_type,
                quoted_speaker=str(record.get("quoted_speaker") or "").strip(),
                quoted_content=join_visual_wraps(str(record.get("quoted_content") or "")),
            )
        )
    if not messages:
        raise ValueError("chat OCR JSON contains no readable messages")
    return tuple(messages)


def chat_message_record(message: ChatMessage) -> dict[str, str]:
    return {
        "speaker": message.speaker,
        "content": message.content,
        "timestamp": message.timestamp,
        "message_type": message.message_type,
        "quoted_speaker": message.quoted_speaker,
        "quoted_content": message.quoted_content,
    }


def render_chat_messages(messages: Sequence[ChatMessage]) -> str:
    rendered = []
    for message in messages:
        timestamp = f" ({message.timestamp})" if message.timestamp else ""
        blocks = []
        if message.quoted_content:
            quoted_speaker = message.quoted_speaker or "[quoted speaker]"
            quoted_text = message.quoted_content.replace("\n", "\n> ")
            blocks.append(f"> **{quoted_speaker}**: {quoted_text}")
        blocks.append(f"**{message.speaker}**{timestamp}: {message.content}")
        rendered.append("\n\n".join(blocks))
    return "\n\n".join(rendered)


def recognition_fingerprint(
    chunk: Chunk,
    total: int,
    mode: str,
    custom_prompt: str | None,
) -> str:
    payload = {
        "prompt_version": OCR_PROMPT_VERSION,
        "image_sha256": chunk.image_sha256,
        "chunk_index": chunk.index,
        "chunk_total": total,
        "mode": mode,
        "custom_prompt": custom_prompt.strip() if custom_prompt else "",
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_glance(command: Sequence[str], timeout: float, chunk_index: int) -> str:
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RuntimeError(f"chunk {chunk_index}: glance failed: {detail}")
    text = completed.stdout.strip()
    if not text:
        raise RuntimeError(f"chunk {chunk_index}: glance returned an empty transcription")
    return text


def recognize_chunk(
    chunk: Chunk,
    total: int,
    glance_command: Sequence[str],
    mode: str,
    custom_prompt: str | None,
    timeout: float,
    resume: bool,
) -> Transcript:
    output_path = chunk.image_path.with_suffix(".ocr.json" if mode == "chat" else ".ocr.md")
    hash_path = output_path.with_name(output_path.name + ".sha256")
    fingerprint = recognition_fingerprint(chunk, total, mode, custom_prompt)
    if (
        resume
        and output_path.is_file()
        and hash_path.is_file()
        and hash_path.read_text(encoding="utf-8").strip() == fingerprint
    ):
        stored = output_path.read_text(encoding="utf-8").strip()
        if mode == "chat":
            messages = parse_chat_messages(stored)
            return Transcript(chunk, render_chat_messages(messages), output_path, True, messages)
        return Transcript(chunk, stored, output_path, True)

    prompt = ocr_prompt(mode, chunk.index, total, custom_prompt)
    messages: tuple[ChatMessage, ...] = ()
    if mode == "chat":
        retry_note = (
            " Return compact valid JSON only. Escape every newline inside a JSON string as "
            "\\n, close every quote and brace, and do not use a Markdown code fence."
        )
        parse_error: ValueError | None = None
        for attempt in range(2):
            attempt_prompt = prompt + (retry_note if attempt else "")
            command = [*glance_command, str(chunk.image_path), "--query", attempt_prompt]
            text = run_glance(command, timeout, chunk.index)
            try:
                messages = parse_chat_messages(text)
                break
            except ValueError as exc:
                parse_error = exc
                if attempt == 0:
                    print(
                        f"retrying chunk {chunk.index}/{total} after invalid chat JSON",
                        file=sys.stderr,
                    )
        else:
            raise RuntimeError(f"chunk {chunk.index}: {parse_error}") from parse_error
    else:
        command = [*glance_command, str(chunk.image_path), "--ocr", prompt]
        text = run_glance(command, timeout, chunk.index)
    if mode == "chat":
        stored = json.dumps(
            {"messages": [chat_message_record(message) for message in messages]},
            ensure_ascii=False,
            indent=2,
        )
        atomic_write_text(output_path, stored + "\n")
        text = render_chat_messages(messages)
    else:
        atomic_write_text(output_path, text + "\n")
    atomic_write_text(hash_path, fingerprint + "\n")
    return Transcript(chunk, text, output_path, False, messages)


def recognize_chunks(
    chunks: Sequence[Chunk],
    glance_command: Sequence[str],
    mode: str,
    custom_prompt: str | None,
    timeout: float,
    jobs: int,
    resume: bool,
) -> list[Transcript]:
    results: dict[int, Transcript] = {}
    worker_count = min(max(1, jobs), len(chunks))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                recognize_chunk,
                chunk,
                len(chunks),
                glance_command,
                mode,
                custom_prompt,
                timeout,
                resume,
            ): chunk
            for chunk in chunks
        }
        try:
            for future in as_completed(futures):
                transcript = future.result()
                results[transcript.chunk.index] = transcript
                state = "reused" if transcript.reused else "recognized"
                print(
                    f"{state} chunk {transcript.chunk.index}/{len(chunks)}",
                    file=sys.stderr,
                )
        except Exception:
            for future in futures:
                future.cancel()
            raise
    return [results[index] for index in sorted(results)]


def trim_outer_blank_lines(text: str) -> list[str]:
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def normalized_line(line: str) -> str:
    normalized = unicodedata.normalize("NFKC", line)
    return " ".join(normalized.casefold().split())


def find_text_overlap(previous: Sequence[str], current: Sequence[str]) -> tuple[int, str]:
    maximum = min(24, len(previous), len(current))
    for count in range(maximum, 0, -1):
        left = [normalized_line(line) for line in previous[-count:]]
        right = [normalized_line(line) for line in current[:count]]
        if left == right and any(left):
            return count, "exact"

    for count in range(min(3, maximum), 0, -1):
        left = [normalized_line(line) for line in previous[-count:]]
        right = [normalized_line(line) for line in current[:count]]
        joined_length = sum(len(line) for line in left + right)
        if joined_length < 24 or not all(left) or not all(right):
            continue
        ratios = [SequenceMatcher(None, a, b).ratio() for a, b in zip(left, right)]
        if min(ratios) >= 0.92 and sum(ratios) / len(ratios) >= 0.96:
            return count, "fuzzy"
    return 0, "none"


def message_fingerprint(message: ChatMessage) -> tuple[str, str, str]:
    def simplify(value: str) -> str:
        return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()

    return (
        simplify(message.speaker),
        simplify(message.content),
        simplify(message.quoted_content),
    )


def unreadable_speaker(value: str) -> bool:
    lowered = value.casefold()
    return not value.strip() or "unreadable" in lowered or "clipped" in lowered


def high_confidence_message_match(left: ChatMessage, right: ChatMessage) -> bool:
    if (left.message_type == "system") != (right.message_type == "system"):
        return False

    left_speaker, left_content, left_quote = message_fingerprint(left)
    right_speaker, right_content, right_quote = message_fingerprint(right)
    speakers_match = (
        left_speaker == right_speaker
        or unreadable_speaker(left.speaker)
        or unreadable_speaker(right.speaker)
    )
    timestamps_match = (
        not left.timestamp
        or not right.timestamp
        or left.timestamp == right.timestamp
    )
    quotes_match = (
        not left_quote
        or not right_quote
        or left_quote == right_quote
    )
    if not speakers_match or not timestamps_match or not quotes_match:
        return False
    if left_content == right_content and left_content:
        return True
    if min(len(left_content), len(right_content)) < 32:
        return False
    return SequenceMatcher(None, left_content, right_content).ratio() >= 0.97


def richer_text(left: str, right: str) -> str:
    def score(value: str) -> tuple[int, int, int]:
        lowered = value.casefold()
        marker_penalty = lowered.count("[clipped]") + lowered.count("[unreadable]")
        return (-marker_penalty, value.count("\n"), len(value))

    return max((left, right), key=score)


def merge_duplicate_message(left: ChatMessage, right: ChatMessage) -> ChatMessage:
    speaker = left.speaker
    if unreadable_speaker(speaker) and not unreadable_speaker(right.speaker):
        speaker = right.speaker
    quoted_speaker = left.quoted_speaker
    if unreadable_speaker(quoted_speaker) and not unreadable_speaker(right.quoted_speaker):
        quoted_speaker = right.quoted_speaker
    return replace(
        left,
        speaker=speaker,
        content=richer_text(left.content, right.content),
        timestamp=left.timestamp or right.timestamp,
        message_type=(
            right.message_type
            if left.message_type == "message" and right.message_type != "message"
            else left.message_type
        ),
        quoted_speaker=quoted_speaker,
        quoted_content=richer_text(left.quoted_content, right.quoted_content),
    )


def canonicalize_speakers(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    def key(value: str) -> str:
        return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()

    variants: dict[str, set[str]] = {}
    for message in messages:
        for value in (message.speaker, message.quoted_speaker):
            if value:
                variants.setdefault(key(value), set()).add(value)
    canonical = {
        fingerprint: min(
            choices,
            key=lambda value: (sum(char.isspace() for char in value), len(value), value),
        )
        for fingerprint, choices in variants.items()
    }
    return [
        replace(
            message,
            speaker=canonical.get(key(message.speaker), message.speaker),
            quoted_speaker=(
                canonical.get(key(message.quoted_speaker), message.quoted_speaker)
                if message.quoted_speaker
                else ""
            ),
        )
        for message in messages
    ]


def find_message_overlap(
    previous: Sequence[ChatMessage], current: Sequence[ChatMessage]
) -> tuple[int, str]:
    maximum = min(8, len(previous), len(current))
    for count in range(maximum, 0, -1):
        left = [message_fingerprint(message) for message in previous[-count:]]
        right = [message_fingerprint(message) for message in current[:count]]
        if left == right and any(any(part for part in item) for item in left):
            return count, "message-exact"
    for count in range(maximum, 0, -1):
        pairs = zip(previous[-count:], current[:count])
        if all(high_confidence_message_match(left, right) for left, right in pairs):
            return count, "message-fuzzy"
    return 0, "none"


def merge_general_transcripts(
    transcripts: Sequence[Transcript],
) -> tuple[str, list[dict[str, int | str]]]:
    merged: list[str] = []
    boundaries = []
    for position, transcript in enumerate(transcripts):
        current = trim_outer_blank_lines(transcript.text)
        if position == 0:
            merged.extend(current)
            continue
        previous_chunk = transcripts[position - 1].chunk
        pixel_overlap = previous_chunk.bottom_overlap + transcript.chunk.top_overlap
        if pixel_overlap:
            overlap_lines, method = find_text_overlap(merged, current)
        else:
            overlap_lines, method = 0, "not-needed"
        boundaries.append(
            {
                "after_chunk": transcripts[position - 1].chunk.index,
                "before_chunk": transcript.chunk.index,
                "removed_items": overlap_lines,
                "unit": "lines",
                "method": method,
            }
        )
        merged.extend(current[overlap_lines:])
    return "\n".join(merged).strip() + "\n", boundaries


def merge_chat_transcripts(
    transcripts: Sequence[Transcript],
) -> tuple[str, list[dict[str, int | str]]]:
    merged: list[ChatMessage] = []
    boundaries = []
    for position, transcript in enumerate(transcripts):
        current = list(transcript.messages)
        if position == 0:
            merged.extend(current)
            continue
        previous_chunk = transcripts[position - 1].chunk
        pixel_overlap = previous_chunk.bottom_overlap + transcript.chunk.top_overlap
        removed, method = (
            find_message_overlap(merged, current) if pixel_overlap else (0, "not-needed")
        )
        if removed:
            merged[-removed:] = [
                merge_duplicate_message(left, right)
                for left, right in zip(merged[-removed:], current[:removed])
            ]
        boundaries.append(
            {
                "after_chunk": previous_chunk.index,
                "before_chunk": transcript.chunk.index,
                "removed_items": removed,
                "unit": "messages",
                "method": method,
            }
        )
        merged.extend(current[removed:])
    return render_chat_messages(canonicalize_speakers(merged)).strip() + "\n", boundaries


def merge_transcripts(
    transcripts: Sequence[Transcript],
) -> tuple[str, list[dict[str, int | str]]]:
    if transcripts and all(transcript.messages for transcript in transcripts):
        return merge_chat_transcripts(transcripts)
    return merge_general_transcripts(transcripts)


def chunk_record(chunk: Chunk, transcript: Transcript | None = None) -> dict[str, object]:
    record: dict[str, object] = {
        "index": chunk.index,
        "image": chunk.image_path.name,
        "image_sha256": chunk.image_sha256,
        "core_top": chunk.core_top,
        "core_bottom": chunk.core_bottom,
        "crop_top": chunk.crop_top,
        "crop_bottom": chunk.crop_bottom,
        "top_overlap": chunk.top_overlap,
        "bottom_overlap": chunk.bottom_overlap,
        "cut_energy": chunk.cut_energy,
        "cut_quality": chunk.cut_quality,
        "top_safe_margin": chunk.top_safe_margin,
        "bottom_safe_margin": chunk.bottom_safe_margin,
    }
    if transcript is not None:
        record.update(
            {
                "ocr": transcript.output_path.name,
                "ocr_reused": transcript.reused,
            }
        )
    return record


def write_manifest(
    path: Path,
    input_path: Path,
    image_size: tuple[int, int],
    mode: str,
    split_sizes: tuple[int, int, int, int],
    analysis: dict[str, float],
    chunks: Sequence[Chunk],
    transcripts: Sequence[Transcript] | None = None,
    boundaries: Sequence[dict[str, int | str]] | None = None,
    output_path: Path | None = None,
) -> None:
    transcript_by_index = {
        transcript.chunk.index: transcript for transcript in transcripts or []
    }
    target, minimum, maximum, overlap = split_sizes
    payload = {
        "schema_version": 1,
        "input": str(input_path),
        "image_width": image_size[0],
        "image_height": image_size[1],
        "mode": mode,
        "target_height": target,
        "min_height": minimum,
        "max_height": maximum,
        "fallback_overlap": overlap,
        "analysis": analysis,
        "chunks": [
            chunk_record(chunk, transcript_by_index.get(chunk.index)) for chunk in chunks
        ],
        "merge_boundaries": list(boundaries or []),
        "output": str(output_path) if output_path else None,
        "complete": transcripts is not None,
    }
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def write_audit(
    path: Path,
    input_path: Path,
    chunks: Sequence[Chunk],
    boundaries: Sequence[dict[str, int | str]],
) -> None:
    boundary_by_after = {int(item["after_chunk"]): item for item in boundaries}
    lines = [
        "# Long-screenshot OCR audit",
        "",
        f"- Source: `{input_path}`",
        f"- Chunks: {len(chunks)}",
        "",
        "| Boundary | Pixel overlap | Removed overlap | Match | Review |",
        "|---|---:|---:|---|---|",
    ]
    if len(chunks) == 1:
        lines.append("| none | 0 px | 0 | none | no |")
    for position, chunk in enumerate(chunks[:-1]):
        boundary = boundary_by_after.get(chunk.index, {})
        pixel_overlap = chunk.bottom_overlap + chunks[position + 1].top_overlap
        removed = int(boundary.get("removed_items", 0))
        unit = str(boundary.get("unit", "lines"))
        method = str(boundary.get("method", "none"))
        review = "yes" if pixel_overlap > 0 or method == "fuzzy" else "no"
        lines.append(
            f"| {chunk.index} -> {chunk.index + 1} | {pixel_overlap}px | "
            f"{removed} {unit} | {method} | {review} |"
        )
    lines.extend(
        [
            "",
            "Review every boundary marked `yes` against the two adjacent chunk images. "
            "The merger removes only exact or very high-confidence repeated lines or messages.",
            "",
        ]
    )
    atomic_write_text(path, "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="long_screenshot_ocr",
        description="Safely split a tall screenshot, OCR each chunk with glance, and merge it",
    )
    parser.add_argument("input", type=Path, help="long screenshot path")
    parser.add_argument(
        "--mode",
        choices=("general", "chat"),
        default="general",
        help="content mode (default: general)",
    )
    parser.add_argument("-o", "--output", type=Path, help="merged Markdown output path")
    parser.add_argument("--chunks-dir", type=Path, help="chunk images and audit directory")
    parser.add_argument("--target-height", type=int, help="preferred core chunk height")
    parser.add_argument("--min-height", type=int, help="minimum core chunk height")
    parser.add_argument("--max-height", type=int, help="maximum core chunk height")
    parser.add_argument(
        "--overlap",
        type=int,
        help="fallback pixel overlap when no safe low-content cut band is found",
    )
    parser.add_argument("--prompt", help="additional OCR requirements passed to glance")
    parser.add_argument(
        "--jobs",
        type=int,
        default=2,
        help="parallel glance processes (default: 2)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=180,
        help="timeout in seconds for each glance call (default: 180)",
    )
    parser.add_argument(
        "--split-only",
        action="store_true",
        help="write chunks and manifest without calling the vision API",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse OCR sidecars whose chunk, mode, and prompt fingerprint still matches",
    )
    return parser.parse_args()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    args = parse_args()
    if Image is None:
        parser.exit(1, "long_screenshot_ocr: requires Pillow; install pillow first\n")
    if args.jobs <= 0:
        parser.exit(1, "long_screenshot_ocr: --jobs must be greater than zero\n")
    if args.timeout <= 0:
        parser.exit(1, "long_screenshot_ocr: --timeout must be greater than zero\n")

    input_path = args.input.expanduser().resolve()
    if not input_path.is_file():
        parser.exit(1, f"long_screenshot_ocr: image not found: {input_path}\n")
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else input_path.with_name(input_path.stem + ".ocr.md")
    )
    chunks_dir = (
        args.chunks_dir.expanduser().resolve()
        if args.chunks_dir
        else input_path.with_name(input_path.stem + "_chunks")
    )
    manifest_path = chunks_dir / "manifest.json"
    if output_path == input_path:
        parser.exit(1, "long_screenshot_ocr: output must not overwrite the source image\n")
    if chunks_dir.exists() and not chunks_dir.is_dir():
        parser.exit(1, f"long_screenshot_ocr: chunks path is not a directory: {chunks_dir}\n")
    reserved_output = output_path.parent == chunks_dir and (
        output_path.name in {"manifest.json", "ocr_audit.md"}
        or re.fullmatch(r"chunk_\d+\..+", output_path.name)
    )
    if reserved_output:
        parser.exit(1, "long_screenshot_ocr: output conflicts with generated chunk artifacts\n")

    try:
        with Image.open(input_path) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
        split_sizes = resolve_split_sizes(
            image.width,
            args.mode,
            args.target_height,
            args.min_height,
            args.max_height,
            args.overlap,
        )
        target, minimum, maximum, overlap = split_sizes
        ranges, analysis = find_core_ranges(
            image,
            args.mode,
            target,
            minimum,
            maximum,
        )
        chunks = save_chunks(image, ranges, chunks_dir, overlap)
        write_manifest(
            manifest_path,
            input_path,
            image.size,
            args.mode,
            split_sizes,
            analysis,
            chunks,
        )
        if args.split_only:
            print(manifest_path)
            return

        glance_command = resolve_glance_command()
        transcripts = recognize_chunks(
            chunks,
            glance_command,
            args.mode,
            args.prompt,
            args.timeout,
            args.jobs,
            args.resume,
        )
        output_text, boundaries = merge_transcripts(transcripts)
        atomic_write_text(output_path, output_text)
        audit_path = chunks_dir / "ocr_audit.md"
        write_audit(audit_path, input_path, chunks, boundaries)
        write_manifest(
            manifest_path,
            input_path,
            image.size,
            args.mode,
            split_sizes,
            analysis,
            chunks,
            transcripts,
            boundaries,
            output_path,
        )
    except (OSError, ValueError, FileNotFoundError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"long_screenshot_ocr: {exc}\n")
    print(output_path)


if __name__ == "__main__":
    main()
