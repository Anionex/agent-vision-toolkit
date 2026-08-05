#!/usr/bin/env python3
"""Unit test: pdf_pages rendering and per-page glance orchestration."""

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "skills", "vision-tools", "scripts", "pdf_pages.py")

SKIPPED: list[str] = []


def load_module():
    spec = importlib.util.spec_from_loader(
        "pdf_pages_mod",
        importlib.machinery.SourceFileLoader("pdf_pages_mod", SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def note_skip(label: str, reason: str) -> None:
    SKIPPED.append(f"{label} ({reason})")
    print(f"SKIP {label}: {reason}")


def check(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


def poppler_available() -> bool:
    return bool(shutil.which("pdftoppm") and shutil.which("pdfinfo"))


def fake_glance_run(real_run, calls=None, stdout="page description", returncode=0):
    """Wrap subprocess.run: fake glance calls, pass poppler calls through."""
    def wrapper(cmd, **kwargs):
        if str(cmd[0]).endswith("glance"):
            if calls is not None:
                calls.append(list(cmd))
            return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")
        return real_run(cmd, **kwargs)
    return wrapper


def test_parse_page_spec(mod) -> None:
    check(mod.parse_page_spec(None, 10) == list(range(1, 11)), "None means all pages")
    check(mod.parse_page_spec("1-3", 10) == [1, 2, 3], "simple range")
    check(mod.parse_page_spec("1,3,5-7", 10) == [1, 3, 5, 6, 7], "mixed spec")
    check(mod.parse_page_spec("5,1-2", 10) == [1, 2, 5], "dedupe and sort")
    check(mod.parse_page_spec("2-2", 10) == [2], "single-token range")
    for bad in ("a", "1-", "-3", "3-1", "0", "11", "1-11", "1,,2"):
        try:
            mod.parse_page_spec(bad, 10)
        except mod.ScriptError:
            pass
        else:
            raise AssertionError(f"spec {bad!r} must be rejected")
    print("PARSE PAGE SPEC PASS")


def test_contiguous_runs(mod) -> None:
    check(mod._contiguous_runs([]) == [], "empty input")
    check(mod._contiguous_runs([1, 2, 3]) == [(1, 3)], "one run")
    check(mod._contiguous_runs([1, 3]) == [(1, 1), (3, 3)], "singletons")
    check(mod._contiguous_runs([1, 2, 5, 6, 9]) == [(1, 2), (5, 6), (9, 9)], "mixed")
    print("CONTIGUOUS RUNS PASS")


def test_build_page_prompt(mod) -> None:
    query = mod.build_page_prompt(2, 10, "query", "What is the title?")
    check("What is the title?" in query and "Page 2 of 10" in query, "query prompt")
    describe = mod.build_page_prompt(2, 10, "describe", None)
    check("Describe" in describe and "Page 2 of 10" in describe, "describe prompt")
    print("BUILD PAGE PROMPT PASS")


def test_glance_command(mod) -> None:
    png = Path("page-1.png")
    ocr = mod.glance_command(png, "ocr", None, None)
    check(ocr == ["glance", "page-1.png", "--ocr"], "ocr command shape")
    ocr_extra = mod.glance_command(png, "ocr", None, "ignore footers")
    check(ocr_extra == ["glance", "page-1.png", "--ocr", "ignore footers"], "ocr extra appended")
    query = mod.glance_command(png, "query", "Page 1 of 5. What title?", None)
    check(query == ["glance", "page-1.png", "-q", "Page 1 of 5. What title?"], "query command shape")
    print("GLANCE COMMAND PASS")


def test_render_pages(mod) -> None:
    if not poppler_available():
        note_skip("RENDER", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("RENDER", "Pillow not installed")
        return
    with tempfile.TemporaryDirectory() as raw:
        pdf = Path(raw) / "fixture.pdf"
        pages = [Image.new("RGB", (100, 140), (200, 30, 30)),
                 Image.new("RGB", (100, 140), (30, 200, 30)),
                 Image.new("RGB", (100, 140), (30, 30, 200))]
        pages[0].save(pdf, save_all=True, append_images=pages[1:])
        out_dir = Path(raw) / "out"
        out_dir.mkdir()
        rendered = mod.render_pages(pdf, [1, 3], 80, out_dir, shutil.which("pdftoppm"))
        check(len(rendered) == 2, "two pages rendered")
        check([int(p.stem.split("-")[1]) for p in rendered] == [1, 3], "page numbers match")
        check(not (out_dir / "page-2.png").exists(),
              "sparse selection must not render pages in between")
        with Image.open(rendered[0]) as image:
            check(abs(image.size[0] - round(100 * 80 / 72)) <= 1
                  and abs(image.size[1] - round(140 * 80 / 72)) <= 1,
                  f"size {image.size} should follow the DPI")
    print("RENDER PAGES PASS")


def test_describe_pages_flow(mod) -> None:
    calls = []
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run, calls=calls)
    try:
        with tempfile.TemporaryDirectory() as raw:
            pngs = []
            for number in (1, 2):
                path = Path(raw) / f"page-{number}.png"
                path.write_bytes(b"x")
                pngs.append(path)
            text = mod.describe_pages(pngs, [1, 2], 5, "describe", None, None, "/path/glance")
    finally:
        mod.subprocess.run = original_run
    check(len(calls) == 2, "one glance call per page")
    check(all(cmd[0] == "/path/glance" and cmd[2] == "-q" for cmd in calls),
          "calls run through the resolved glance path")
    check("Page 1 of 5" in calls[0][3] and "Page 2 of 5" in calls[1][3], "page context in prompts")
    check("## Page 1 / 5" in text and "## Page 2 / 5" in text, "markdown sections")
    check("page description" in text, "answers included")
    print("DESCRIBE PAGES FLOW PASS")


def test_describe_glance_failure(mod) -> None:
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run, returncode=1, stdout="")
    try:
        with tempfile.TemporaryDirectory() as raw:
            png = Path(raw) / "page-1.png"
            png.write_bytes(b"x")
            try:
                mod.describe_pages([png], [1], 3, "describe", None, None, "glance")
            except mod.ScriptError as exc:
                check("glance failed on page 1" in str(exc), "glance failure surfaces per page")
            else:
                raise AssertionError("failing glance must raise ScriptError")
    finally:
        mod.subprocess.run = original_run
    print("DESCRIBE GLANCE FAILURE PASS")


def test_main_flow(mod) -> None:
    if not shutil.which("glance"):
        note_skip("MAIN FLOW", "glance CLI not on PATH")
        return
    if not poppler_available():
        note_skip("MAIN FLOW", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("MAIN FLOW", "Pillow not installed")
        return
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run)
    try:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "fixture.pdf"
            images = [Image.new("RGB", (60, 60), (10, 10, 10)) for _ in range(3)]
            images[0].save(pdf, save_all=True, append_images=images[1:])
            old_argv = sys.argv
            sys.argv = ["pdf_pages.py", str(pdf), "-p", "1,3", "--dpi", "80"]
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    mod.main()
            finally:
                sys.argv = old_argv
    finally:
        mod.subprocess.run = original_run
    text = buffer.getvalue()
    check("## Page 1 / 3" in text and "## Page 3 / 3" in text, "sections for selected pages")
    check("page description" in text, "descriptions included")
    check("## Page 2 / 3" not in text, "unselected page skipped")
    print("MAIN FLOW PASS")


def test_pdf_page_count(mod) -> None:
    try:
        from PIL import Image
    except ImportError:
        note_skip("PAGE COUNT", "Pillow not installed")
        return
    if not poppler_available():
        note_skip("PAGE COUNT", "poppler (pdftoppm/pdfinfo) not installed")
        return
    with tempfile.TemporaryDirectory() as raw:
        pdf = Path(raw) / "fixture.pdf"
        images = [Image.new("RGB", (30, 30), (0, 0, 0)) for _ in range(3)]
        images[0].save(pdf, save_all=True, append_images=images[1:])
        check(mod.pdf_page_count(pdf, shutil.which("pdfinfo")) == 3, "page count parsed")
        broken = Path(raw) / "broken.pdf"
        broken.write_bytes(b"%PDF-1.3\n%%EOF")
        try:
            mod.pdf_page_count(broken, shutil.which("pdfinfo"))
        except mod.ScriptError:
            pass
        else:
            raise AssertionError("broken PDF must raise ScriptError")
        fake = Path(raw) / "fake-pdfinfo"
        fake.write_text("#!/bin/sh\necho 'Title: whatever'\nexit 0\n")
        fake.chmod(0o755)
        try:
            mod.pdf_page_count(pdf, str(fake))
        except mod.ScriptError:
            pass
        else:
            raise AssertionError("pdfinfo without a Pages: line must raise ScriptError")
    print("PDF PAGE COUNT PASS")


def test_render_pages_failure(mod) -> None:
    original_run = mod.subprocess.run
    try:
        mod.subprocess.run = lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1, stdout="", stderr="boom")
        with tempfile.TemporaryDirectory() as raw:
            out_dir = Path(raw)
            try:
                mod.render_pages(Path(raw) / "x.pdf", [1], 80, out_dir, "pdftoppm")
            except mod.ScriptError as exc:
                check("boom" in str(exc), "pdftoppm stderr surfaces")
            else:
                raise AssertionError("failing pdftoppm must raise ScriptError")
    finally:
        mod.subprocess.run = original_run
    print("RENDER PAGES FAILURE PASS")


def test_subprocess_timeouts(mod) -> None:
    captured: dict = {}

    def timeout_run(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=captured["timeout"])

    original_run = mod.subprocess.run
    mod.subprocess.run = timeout_run
    try:
        try:
            mod.pdf_page_count(Path("x.pdf"), "pdfinfo")
        except mod.ScriptError as exc:
            check("timed out" in str(exc), "pdfinfo timeout surfaces as ScriptError")
        else:
            raise AssertionError("pdfinfo timeout must raise ScriptError")
        check(captured["timeout"] == 30, "pdfinfo timeout is 30s")
        with tempfile.TemporaryDirectory() as raw:
            try:
                mod.render_pages(Path("x.pdf"), [1, 2], 80, Path(raw), "pdftoppm")
            except mod.ScriptError as exc:
                check("timed out" in str(exc) and "--dpi" in str(exc),
                      "pdftoppm timeout carries a mitigation hint")
            else:
                raise AssertionError("pdftoppm timeout must raise ScriptError")
        check(captured["timeout"] == 120, "pdftoppm timeout is 120s")
        with tempfile.TemporaryDirectory() as raw:
            png = Path(raw) / "page-1.png"
            png.write_bytes(b"x")
            try:
                mod.describe_pages([png], [1], 3, "describe", None, None, "glance")
            except mod.ScriptError as exc:
                check("glance timed out on page 1" in str(exc), "glance timeout surfaces")
            else:
                raise AssertionError("glance timeout must raise ScriptError")
        check(captured["timeout"] == 600, "glance timeout is 600s")
    finally:
        mod.subprocess.run = original_run
    print("SUBPROCESS TIMEOUTS PASS")


def test_render_missing_pages(mod) -> None:
    original_run = mod.subprocess.run
    try:
        mod.subprocess.run = lambda *args, **kwargs: types.SimpleNamespace(
            returncode=0, stdout="", stderr="")
        with tempfile.TemporaryDirectory() as raw:
            try:
                mod.render_pages(Path(raw) / "x.pdf", [1, 2], 80, Path(raw), "pdftoppm")
            except mod.ScriptError as exc:
                check("missing pages [1, 2]" in str(exc), "missing-page check fires")
            else:
                raise AssertionError("no output files must raise ScriptError")
    finally:
        mod.subprocess.run = original_run
    print("RENDER MISSING PAGES PASS")


def test_require_missing(mod) -> None:
    original_which = mod.shutil.which
    try:
        mod.shutil.which = lambda name: None
        for require, name in ((mod.require_poppler, "poppler"), (mod.require_glance, "glance")):
            try:
                require()
            except mod.ScriptError as exc:
                check(name in str(exc), f"missing {name} surfaces clearly")
            else:
                raise AssertionError(f"missing {name} must raise ScriptError")
    finally:
        mod.shutil.which = original_which
    print("REQUIRE MISSING PASS")


def test_dpi_invalid(mod) -> None:
    for bad in ("0", "601"):
        old_argv = sys.argv
        sys.argv = ["pdf_pages.py", "deck.pdf", "--dpi", bad]
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                mod.main()
        except SystemExit as exc:
            check(exc.code == 2, f"--dpi {bad} exits 2")
        else:
            raise AssertionError(f"--dpi {bad} must exit nonzero")
        finally:
            sys.argv = old_argv
    print("DPI INVALID PASS")


def test_main_keep_flow(mod) -> None:
    if not shutil.which("glance"):
        note_skip("KEEP FLOW", "glance CLI not on PATH")
        return
    if not poppler_available():
        note_skip("KEEP FLOW", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("KEEP FLOW", "Pillow not installed")
        return
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run)
    try:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "deck.pdf"
            images = [Image.new("RGB", (40, 40), (0, 0, 0)) for _ in range(2)]
            images[0].save(pdf, save_all=True, append_images=images[1:])
            keep_dir = Path(raw) / "keep"
            old_argv = sys.argv
            sys.argv = ["pdf_pages.py", str(pdf), "--keep", str(keep_dir), "--dpi", "80"]
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    mod.main()
            finally:
                sys.argv = old_argv
            check("page description" in buffer.getvalue(), "keep flow describes pages")
            subs = [p for p in keep_dir.iterdir() if p.is_dir()]
            check(len(subs) == 1, "one fresh subdirectory per run")
            pages = sorted(subs[0].glob("page-*.png"))
            check(len(pages) == 2, "rendered pages kept inside the fresh subdirectory")
    finally:
        mod.subprocess.run = original_run
    print("MAIN KEEP FLOW PASS")


def test_keep_dir_failure(mod) -> None:
    if not shutil.which("glance"):
        note_skip("KEEP FAILURE", "glance CLI not on PATH")
        return
    if not poppler_available():
        note_skip("KEEP FAILURE", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("KEEP FAILURE", "Pillow not installed")
        return
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run)
    try:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "deck.pdf"
            images = [Image.new("RGB", (40, 40), (0, 0, 0)) for _ in range(2)]
            images[0].save(pdf, save_all=True, append_images=images[1:])
            keep_dir = Path(raw) / "keep"
            keep_dir.mkdir()
            os.chmod(keep_dir, 0o555)
            old_argv = sys.argv
            sys.argv = ["pdf_pages.py", str(pdf), "--keep", str(keep_dir), "--dpi", "80"]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    mod.main()
            except SystemExit as exc:
                check(exc.code == 1, "unusable --keep directory exits 1")
            else:
                raise AssertionError("unusable --keep directory must fail cleanly")
            finally:
                sys.argv = old_argv
                os.chmod(keep_dir, 0o755)
    finally:
        mod.subprocess.run = original_run
    print("KEEP DIR FAILURE PASS")


def test_keep_collision(mod) -> None:
    if not shutil.which("glance"):
        note_skip("KEEP COLLISION", "glance CLI not on PATH")
        return
    if not poppler_available():
        note_skip("KEEP COLLISION", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("KEEP COLLISION", "Pillow not installed")
        return
    original_run = mod.subprocess.run
    original_strftime = mod.time.strftime
    original_ns = mod.time.time_ns
    mod.subprocess.run = fake_glance_run(original_run)
    try:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "deck.pdf"
            images = [Image.new("RGB", (40, 40), (0, 0, 0)) for _ in range(2)]
            images[0].save(pdf, save_all=True, append_images=images[1:])
            keep = Path(raw) / "keep"
            keep.mkdir()
            mod.time.strftime = lambda fmt: "20260806-000000"
            mod.time.time_ns = lambda: 123456
            (keep / "deck-20260806-000000-123456").mkdir()  # pre-existing collision
            old_argv = sys.argv
            sys.argv = ["pdf_pages.py", str(pdf), "--keep", str(keep), "--dpi", "80"]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    mod.main()
            finally:
                sys.argv = old_argv
            fallback = keep / "deck-20260806-000000-123456-1"
            check(fallback.is_dir(), "collision falls back to a -1 suffix")
            check(len(list(fallback.glob("page-*.png"))) == 2,
                  "pages rendered into the collision fallback directory")
    finally:
        mod.subprocess.run = original_run
        mod.time.strftime = original_strftime
        mod.time.time_ns = original_ns
    print("KEEP COLLISION PASS")


def test_main_modes(mod) -> None:
    if not shutil.which("glance"):
        note_skip("MODES", "glance CLI not on PATH")
        return
    if not poppler_available():
        note_skip("MODES", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("MODES", "Pillow not installed")
        return
    calls = []
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run, calls=calls, stdout="mode description")
    try:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "deck.pdf"
            images = [Image.new("RGB", (40, 40), (0, 0, 0)) for _ in range(2)]
            images[0].save(pdf, save_all=True, append_images=images[1:])
            for argv in (["--ocr"], ["--ocr", "ignore footers"], ["-q", "What title?"]):
                calls.clear()
                old_argv = sys.argv
                sys.argv = ["pdf_pages.py", str(pdf)] + argv + ["--dpi", "80"]
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        mod.main()
                finally:
                    sys.argv = old_argv
                check(len(calls) == 2, f"one glance call per page for {argv}")
                if argv[0] == "--ocr":
                    check(all("--ocr" in cmd for cmd in calls), f"ocr flag passed for {argv}")
                    if len(argv) > 1:
                        check(all(cmd[-1] == "ignore footers" for cmd in calls),
                              "ocr extra reaches glance")
                else:
                    check(all(cmd[2] == "-q" and "What title?" in cmd[3] for cmd in calls),
                          "query text reaches every page prompt")
    finally:
        mod.subprocess.run = original_run
    print("MAIN MODES PASS")


def test_main_exit_code(mod) -> None:
    if not shutil.which("glance"):
        note_skip("EXIT CODE", "glance CLI not on PATH")
        return
    if not poppler_available():
        note_skip("EXIT CODE", "poppler (pdftoppm/pdfinfo) not installed")
        return
    try:
        from PIL import Image
    except ImportError:
        note_skip("EXIT CODE", "Pillow not installed")
        return
    original_run = mod.subprocess.run
    mod.subprocess.run = fake_glance_run(original_run)
    try:
        with tempfile.TemporaryDirectory() as raw:
            pdf = Path(raw) / "deck.pdf"
            images = [Image.new("RGB", (40, 40), (0, 0, 0)) for _ in range(2)]
            images[0].save(pdf, save_all=True, append_images=images[1:])
            old_argv = sys.argv
            sys.argv = ["pdf_pages.py", str(pdf), "-p", "99", "--dpi", "80"]
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    mod.main()
            except SystemExit as exc:
                check(exc.code == 1, "script errors exit 1")
            else:
                raise AssertionError("out-of-range pages must exit nonzero")
            finally:
                sys.argv = old_argv
    finally:
        mod.subprocess.run = original_run
    print("MAIN EXIT CODE PASS")


def main() -> None:
    mod = load_module()
    test_parse_page_spec(mod)
    test_contiguous_runs(mod)
    test_build_page_prompt(mod)
    test_glance_command(mod)
    test_render_pages(mod)
    test_describe_pages_flow(mod)
    test_describe_glance_failure(mod)
    test_main_flow(mod)
    test_pdf_page_count(mod)
    test_render_pages_failure(mod)
    test_subprocess_timeouts(mod)
    test_render_missing_pages(mod)
    test_require_missing(mod)
    test_dpi_invalid(mod)
    test_main_keep_flow(mod)
    test_keep_dir_failure(mod)
    test_keep_collision(mod)
    test_main_modes(mod)
    test_main_exit_code(mod)
    if SKIPPED:
        print("PDF PAGES TEST PASS (SKIPPED: " + "; ".join(SKIPPED) + ")")
    else:
        print("PDF PAGES TEST PASS")


if __name__ == "__main__":
    main()
