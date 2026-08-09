#!/usr/bin/env python3
"""Focused tests for the long-screenshot split, OCR, merge, and resume workflow."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("SKIP: Pillow not installed; long-screenshot OCR is an optional feature")
    sys.exit(0)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "vision-tools" / "scripts" / "long_screenshot_ocr.py"


def load_module():
    spec = importlib.util.spec_from_file_location("long_screenshot_ocr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_chunk(mod, temp_dir, index, *, top_overlap=0, bottom_overlap=0):
    path = Path(temp_dir) / f"chunk_{index:03d}.png"
    Image.new("RGB", (20, 20), "white").save(path)
    return mod.Chunk(
        index=index,
        core_top=(index - 1) * 20,
        core_bottom=index * 20,
        crop_top=(index - 1) * 20 - top_overlap,
        crop_bottom=index * 20 + bottom_overlap,
        top_overlap=top_overlap,
        bottom_overlap=bottom_overlap,
        cut_energy=0.0,
        cut_quality=1.0,
        top_safe_margin=0,
        bottom_safe_margin=0,
        image_path=path,
        image_sha256="fixture",
    )


def test_split_sizes(mod):
    assert mod.resolve_split_sizes(1000, "general", 1000, 600, 1400, 40) == (
        1000,
        600,
        1400,
        40,
    )
    for values in ((0, 600, 1400, 40), (1000, 1200, 1100, 40), (1000, 600, 1400, 300)):
        try:
            mod.resolve_split_sizes(1000, "general", *values)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid split values accepted: {values}")


def test_safe_cuts_land_in_blank_bands(mod):
    image = Image.new("RGB", (300, 1400), "white")
    draw = ImageDraw.Draw(image)
    for block_top in (20, 420, 820, 1220):
        for row in range(block_top, min(block_top + 280, image.height), 24):
            draw.rectangle((20, row, 280, row + 8), fill="black")

    ranges, _analysis = mod.find_core_ranges(
        image,
        "general",
        target_height=400,
        min_height=300,
        max_height=500,
    )
    cuts = [item.bottom for item in ranges[:-1]]
    assert len(cuts) >= 2, cuts
    for cut in cuts:
        band = image.crop((0, max(0, cut - 3), image.width, min(image.height, cut + 4)))
        assert band.getextrema() == ((255, 255), (255, 255), (255, 255)), cut


def test_safe_cut_does_not_use_blank_space_inside_a_bubble(mod):
    image = Image.new("RGB", (900, 900), (218, 230, 235))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((55, 250, 330, 475), radius=12, fill="white")
    draw.text((69, 270), "Message heading", fill="black")
    draw.rounded_rectangle((69, 315, 318, 450), radius=8, fill=(238, 241, 242))
    draw.text((80, 330), "status: ready", fill="black")
    draw.text((80, 390), "build: 1.0.0", fill="black")

    ranges, _analysis = mod.find_core_ranges(
        image,
        "chat",
        target_height=380,
        min_height=260,
        max_height=500,
    )
    cut = ranges[0].bottom
    assert not 250 <= cut <= 475, f"cut {cut} landed inside the message bubble"


def test_overlap_policy_and_text_merge(mod):
    with tempfile.TemporaryDirectory() as temp_dir:
        first = make_chunk(mod, temp_dir, 1, bottom_overlap=40)
        second = make_chunk(mod, temp_dir, 2, top_overlap=40)
        first_text = mod.Transcript(
            first, "alpha\nshared line", first.image_path.with_suffix(".ocr.md"), False
        )
        second_text = mod.Transcript(
            second, "shared line\nbeta", second.image_path.with_suffix(".ocr.md"), False
        )
        merged, boundaries = mod.merge_transcripts([first_text, second_text])
        assert merged == "alpha\nshared line\nbeta\n", merged
        assert boundaries[0]["removed_items"] == 1
        assert boundaries[0]["method"] == "exact"

        safe_first = make_chunk(mod, temp_dir, 1)
        safe_second = make_chunk(mod, temp_dir, 2)
        repeated = mod.merge_transcripts(
            [
                mod.Transcript(safe_first, "alpha\nrepeat", Path("one.md"), False),
                mod.Transcript(safe_second, "repeat\nbeta", Path("two.md"), False),
            ]
        )[0]
        assert repeated == "alpha\nrepeat\nrepeat\nbeta\n", repeated


def test_chat_json_render_and_message_merge(mod):
    raw = json.dumps(
        {
            "messages": [
                {
                    "speaker": "Alice",
                    "content": "first line\nwrapped line",
                    "timestamp": "10:30",
                    "message_type": "message",
                    "quoted_speaker": "",
                    "quoted_content": "",
                },
                {
                    "speaker": "Bob",
                    "content": "reply",
                    "timestamp": "",
                    "message_type": "message",
                    "quoted_speaker": "Alice",
                    "quoted_content": "first line",
                },
            ]
        }
    )
    messages = mod.parse_chat_messages(raw)
    rendered = mod.render_chat_messages(messages)
    assert "**Alice** (10:30): first line wrapped line" in rendered
    assert "> **Alice**: first line" in rendered

    with tempfile.TemporaryDirectory() as temp_dir:
        first = make_chunk(mod, temp_dir, 1, bottom_overlap=30)
        second = make_chunk(mod, temp_dir, 2, top_overlap=30)
        one = mod.Transcript(first, rendered, Path("one.json"), False, messages)
        two_messages = (messages[-1], mod.ChatMessage("Alice", "final"))
        two = mod.Transcript(
            second,
            mod.render_chat_messages(two_messages),
            Path("two.json"),
            False,
            two_messages,
        )
        merged, boundaries = mod.merge_transcripts([one, two])
        assert merged.count("**Bob**") == 1, merged
        assert "**Alice**: final" in merged
    assert boundaries[0]["removed_items"] == 1
    assert boundaries[0]["unit"] == "messages"
    assert mod.normalize_timestamp("2026-08-06 10:30") == "2026-08-06 10:30"
    assert mod.normalize_timestamp("2026-08-06 10:3") == ""
    assert mod.normalize_timestamp("[clipped]") == ""
    assert mod.join_visual_wraps(
        "Uploading now.\nreport.pdf\n194 KB · PDF document",
        preserve_lines=True,
    ) == "Uploading now.\nreport.pdf\n194 KB · PDF document"
    assert mod.join_visual_wraps(
        "Confirm the gates:\nAre all gates green?\nAnonymous Poll\n• QA\n• Monitoring"
    ) == "Confirm the gates:\nAre all gates green?\nAnonymous Poll\n• QA\n• Monitoring"


def test_chat_overlap_uses_richer_boundary_messages(mod):
    with tempfile.TemporaryDirectory() as temp_dir:
        first = make_chunk(mod, temp_dir, 1, bottom_overlap=64)
        second = make_chunk(mod, temp_dir, 2, top_overlap=64)
        prior_messages = (
            mod.ChatMessage(
                "Priya Shah",
                "Help center article is published but unlisted.",
                "10:12",
            ),
            mod.ChatMessage("You", "Deployment started."),
        )
        repeated_messages = (
            mod.ChatMessage(
                "[unreadable speaker]",
                "Help center article is published but unlisted.",
                "10:12",
            ),
            mod.ChatMessage("You", "Deployment started.", "10:15"),
            mod.ChatMessage("Noah Wilson", "25% complete.", "10:22"),
        )
        merged, boundaries = mod.merge_transcripts(
            [
                mod.Transcript(first, "", Path("one.json"), False, prior_messages),
                mod.Transcript(second, "", Path("two.json"), False, repeated_messages),
            ]
        )
        assert merged.count("Help center article is published") == 1, merged
        assert merged.count("Deployment started") == 1, merged
        assert "**Priya Shah** (10:12)" in merged, merged
        assert "**You** (10:15): Deployment started." in merged, merged
        assert "[unreadable speaker]" not in merged, merged
        assert boundaries[0]["removed_items"] == 2
        assert boundaries[0]["method"] == "message-fuzzy"


def test_resume_fingerprint_tracks_mode_and_prompt(mod):
    chat_prompt = mod.ocr_prompt("chat", 1, 2, None)
    assert "use You as the speaker" in chat_prompt
    assert "unread divider as a system message" in chat_prompt
    assert "write each option as a bullet line" in chat_prompt

    with tempfile.TemporaryDirectory() as temp_dir:
        chunk = make_chunk(mod, temp_dir, 1)
        base = mod.recognition_fingerprint(chunk, 2, "general", None)
        assert base == mod.recognition_fingerprint(chunk, 2, "general", None)
        assert base != mod.recognition_fingerprint(chunk, 3, "general", None)
        assert base != mod.recognition_fingerprint(chunk, 2, "chat", None)
        assert base != mod.recognition_fingerprint(chunk, 2, "general", "keep columns")


def write_stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    if os.name == "nt":
        # Windows cannot exec a shebang script and shutil.which only matches
        # PATHEXT suffixes, so also install a .cmd wrapper that runs the stub.
        cmd_file = path.with_suffix(".cmd")
        cmd_file.write_text(
            f'@echo off\r\n"{sys.executable}" "{path.resolve()}" %*\r\n',
            encoding="ascii",
        )


def test_cli_split_ocr_merge_and_resume():
    with tempfile.TemporaryDirectory() as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source = temp_dir / "long.png"
        image = Image.new("RGB", (240, 980), "white")
        draw = ImageDraw.Draw(image)
        for row in range(20, 960, 36):
            draw.rectangle((12, row, 228, row + 7), fill="black")
        image.save(source)

        chunks_dir = temp_dir / "chunks"
        output = temp_dir / "result.md"
        split = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(source),
                "--split-only",
                "--target-height",
                "350",
                "--min-height",
                "250",
                "--max-height",
                "450",
                "--chunks-dir",
                str(chunks_dir),
            ],
            text=True,
            capture_output=True,
            check=True,
        )
        manifest_path = Path(split.stdout.strip())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert not manifest["complete"]
        assert len(manifest["chunks"]) >= 2

        overwrite = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(source),
                "--split-only",
                "-o",
                str(source),
            ],
            text=True,
            capture_output=True,
        )
        assert overwrite.returncode != 0
        assert "must not overwrite" in overwrite.stderr
        with Image.open(source) as preserved:
            assert preserved.size == (240, 980)

        stub = temp_dir / "glance"
        write_stub(
            stub,
            "from pathlib import Path\n"
            "import sys\n"
            "print(Path(sys.argv[1]).stem)\n",
        )
        command = [
            sys.executable,
            str(SCRIPT),
            str(source),
            "--target-height",
            "350",
            "--min-height",
            "250",
            "--max-height",
            "450",
            "--chunks-dir",
            str(chunks_dir),
            "--jobs",
            "2",
            "-o",
            str(output),
        ]
        environment = os.environ.copy()
        environment["PATH"] = str(temp_dir) + os.pathsep + environment.get("PATH", "")
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        assert Path(completed.stdout.strip()) == output.resolve(), (
            completed.stdout,
            completed.stderr,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = "\n".join(Path(item["image"]).stem for item in manifest["chunks"]) + "\n"
        assert output.read_text(encoding="utf-8") == expected
        assert manifest["complete"]
        assert (chunks_dir / "ocr_audit.md").is_file()

        write_stub(stub, "import sys\nsys.exit(9)\n")
        resumed = subprocess.run(
            [*command, "--resume"],
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        assert "reused chunk" in resumed.stderr
        assert output.read_text(encoding="utf-8") == expected


def test_cli_chat_mode_uses_structured_messages():
    with tempfile.TemporaryDirectory() as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source = temp_dir / "chat.png"
        image = Image.new("RGB", (220, 620), "white")
        draw = ImageDraw.Draw(image)
        for row in range(20, 600, 32):
            draw.rectangle((12, row, 208, row + 6), fill="black")
        image.save(source)

        stub = temp_dir / "glance"
        write_stub(
            stub,
            "import json\n"
            "from pathlib import Path\n"
            "import sys\n"
            "index = int(Path(sys.argv[1]).stem.rsplit('_', 1)[1])\n"
            "print(json.dumps({'messages': [{'speaker': 'User', "
            "'content': f'message-{index}', 'timestamp': '', "
            "'message_type': 'message', 'quoted_speaker': '', "
            "'quoted_content': ''}]}))\n",
        )
        environment = os.environ.copy()
        environment["PATH"] = str(temp_dir) + os.pathsep + environment.get("PATH", "")
        chunks_dir = temp_dir / "chat_chunks"
        output = temp_dir / "chat.md"
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(source),
                "--mode",
                "chat",
                "--target-height",
                "260",
                "--min-height",
                "200",
                "--max-height",
                "320",
                "--chunks-dir",
                str(chunks_dir),
                "-o",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        manifest = json.loads((chunks_dir / "manifest.json").read_text(encoding="utf-8"))
        expected = "\n\n".join(
            f"**User**: message-{item['index']}" for item in manifest["chunks"]
        ) + "\n"
        assert output.read_text(encoding="utf-8") == expected
        assert all(str(item["ocr"]).endswith(".ocr.json") for item in manifest["chunks"])


def test_cli_chat_mode_retries_invalid_json_once():
    with tempfile.TemporaryDirectory() as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source = temp_dir / "chat.png"
        Image.new("RGB", (220, 260), "white").save(source)
        state = temp_dir / "attempted"
        stub = temp_dir / "glance"
        write_stub(
            stub,
            "import json\n"
            "from pathlib import Path\n"
            f"state = Path({str(state)!r})\n"
            "if not state.exists():\n"
            "    state.write_text('1')\n"
            "    print('{\\\"messages\\\":[{\\\"speaker\\\":\\\"User\\\"')\n"
            "else:\n"
            "    print(json.dumps({'messages': [{'speaker': 'User', "
            "'content': 'recovered', 'timestamp': '', 'message_type': 'message', "
            "'quoted_speaker': '', 'quoted_content': ''}]}))\n",
        )
        environment = os.environ.copy()
        environment["PATH"] = str(temp_dir) + os.pathsep + environment.get("PATH", "")
        output = temp_dir / "chat.md"
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                str(source),
                "--mode",
                "chat",
                "-o",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        assert "retrying chunk 1/1 after invalid chat JSON" in completed.stderr
        assert output.read_text(encoding="utf-8") == "**User**: recovered\n"


def main():
    mod = load_module()
    test_split_sizes(mod)
    test_safe_cuts_land_in_blank_bands(mod)
    test_safe_cut_does_not_use_blank_space_inside_a_bubble(mod)
    test_overlap_policy_and_text_merge(mod)
    test_chat_json_render_and_message_merge(mod)
    test_chat_overlap_uses_richer_boundary_messages(mod)
    test_resume_fingerprint_tracks_mode_and_prompt(mod)
    test_cli_split_ocr_merge_and_resume()
    test_cli_chat_mode_uses_structured_messages()
    test_cli_chat_mode_retries_invalid_json_once()
    subprocess.run([sys.executable, str(SCRIPT), "--help"], check=True, stdout=subprocess.DEVNULL)
    print("LONG SCREENSHOT OCR TEST PASS")


if __name__ == "__main__":
    main()
