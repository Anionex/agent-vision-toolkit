#!/usr/bin/env python3
"""pdf_pages: render a PDF's pages and describe each one via the glance CLI.

A thin local script in the same spirit as pixel_diff.py: it orchestrates
existing tools instead of depending on this repo's Python modules. It
renders the selected pages with poppler's pdftoppm and lets the glance CLI
(already installed by the toolkit install) describe each page, so the
script itself stays self-contained.

Run from this skill's directory (paths are relative to it, like the other
scripts here):

    python3 scripts/pdf_pages.py deck.pdf -p 1-3,5,7-9 --ocr

Requires poppler (pdftoppm + pdfinfo) and the glance CLI on PATH; fails
with a clear error instead of guessing when either is missing.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path


class ScriptError(RuntimeError):
    """A safe, user-facing script failure."""


_PAGE_SPEC_TOKEN = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*$")

DEFAULT_DESCRIBE_PROMPT = "Describe the contents of this page in detail."


def require_poppler() -> tuple[str, str]:
    pdftoppm = shutil.which("pdftoppm")
    pdfinfo = shutil.which("pdfinfo")
    if not pdftoppm or not pdfinfo:
        raise ScriptError(
            "pdf_pages requires poppler's pdftoppm and pdfinfo; "
            "install poppler first, e.g. 'brew install poppler'"
        )
    return pdftoppm, pdfinfo


def require_glance() -> str:
    glance = shutil.which("glance")
    if not glance:
        raise ScriptError(
            "pdf_pages requires the glance CLI on PATH; "
            "install the agent-vision-toolkit CLIs first (see AGENT_INSTALL.md)"
        )
    return glance


def pdf_page_count(pdf_path: Path, pdfinfo: str) -> int:
    try:
        proc = subprocess.run([pdfinfo, str(pdf_path)], capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise ScriptError(f"pdfinfo timed out on {pdf_path}") from exc
    if proc.returncode != 0:
        raise ScriptError(f"pdfinfo failed on {pdf_path}: {proc.stderr.strip() or proc.stdout.strip()}")
    for line in proc.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                break
    raise ScriptError(f"pdfinfo did not report a page count for {pdf_path}")


def parse_page_spec(spec: str | None, total: int) -> list[int]:
    """Parse a 1-based page range like '1-3,5,7-9' into an ordered, deduplicated page list."""
    if spec is None:
        return list(range(1, total + 1))
    pages: list[int] = []
    for token in spec.split(","):
        match = _PAGE_SPEC_TOKEN.match(token)
        if not match:
            raise ScriptError(f"Invalid page range {token!r} (expected forms like '3', '1-3', or '1,3-5')")
        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
        if start > end:
            raise ScriptError(f"Invalid page range {token!r}: start is after end")
        if start < 1 or end > total:
            raise ScriptError(f"Page range {token!r} is out of range for a {total}-page PDF")
        pages.extend(range(start, end + 1))
    return sorted(set(pages))


def _contiguous_runs(pages: list[int]) -> list[tuple[int, int]]:
    """Split a sorted page list into (start, end) contiguous runs."""
    if not pages:
        return []
    runs: list[tuple[int, int]] = []
    start = prev = pages[0]
    for number in pages[1:]:
        if number == prev + 1:
            prev = number
        else:
            runs.append((start, prev))
            start = prev = number
    runs.append((start, prev))
    return runs


def render_pages(pdf_path: Path, pages: list[int], dpi: int, out_dir: Path,
                 pdftoppm: str) -> list[Path]:
    # Render each contiguous run separately so a sparse selection like
    # -p 1,600 never renders the 598 pages in between.
    produced: dict[int, Path] = {}
    for start, end in _contiguous_runs(pages):
        prefix = out_dir / "page"
        try:
            proc = subprocess.run(
                [pdftoppm, "-png", "-r", str(dpi), "-f", str(start), "-l", str(end),
                 str(pdf_path), str(prefix)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise ScriptError(
                f"pdftoppm timed out on {pdf_path} (pages {start}-{end}); "
                "try a smaller --pages range or a lower --dpi"
            ) from exc
        if proc.returncode != 0:
            raise ScriptError(
                f"pdftoppm failed on {pdf_path} (pages {start}-{end}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        for image in out_dir.glob("page-*.png"):
            try:
                produced[int(image.stem.split("-")[1])] = image
            except (IndexError, ValueError):
                continue
    missing = [n for n in pages if n not in produced]
    if missing:
        raise ScriptError(f"pdftoppm output is missing pages {missing}")
    return [produced[n] for n in pages]


def build_page_prompt(page_no: int, total: int, mode: str, query: str | None) -> str:
    context = f"Page {page_no} of {total} in this PDF document."
    if mode == "query":
        return f"{context}\n{query}"
    return f"{context} {DEFAULT_DESCRIBE_PROMPT}"


def glance_command(image_path: Path, mode: str, prompt: str | None,
                   ocr_extra: str | None) -> list[str]:
    if mode == "ocr":
        command = ["glance", str(image_path), "--ocr"]
        if ocr_extra:
            command.append(ocr_extra)
        return command
    return ["glance", str(image_path), "-q", prompt]


def describe_pages(image_paths: list[Path], pages: list[int], total: int,
                   mode: str, query: str | None, ocr_extra: str | None,
                   glance: str) -> str:
    sections = []
    for page_no, image_path in zip(pages, image_paths):
        prompt = build_page_prompt(page_no, total, mode, query) if mode != "ocr" else None
        command = glance_command(image_path, mode, prompt, ocr_extra)
        command[0] = glance
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired as exc:
            raise ScriptError(f"glance timed out on page {page_no}") from exc
        if proc.returncode != 0:
            raise ScriptError(
                f"glance failed on page {page_no}: {proc.stderr.strip() or proc.stdout.strip()}"
            )
        answer = proc.stdout.strip()
        if not answer:
            raise ScriptError(f"glance returned no output for page {page_no}")
        sections.append(f"## Page {page_no} / {total}\n\n{answer}\n")
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pdf_pages",
        description="Render PDF pages to images and describe each page via the glance CLI",
    )
    parser.add_argument("pdf", type=Path, help="path to the PDF file")
    parser.add_argument("-p", "--pages", metavar="SPEC",
                        help="1-based page range to process, e.g. '1-3,5,7-9' (default: all pages)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-q", "--query", help="ask a question about every selected page")
    group.add_argument("--ocr", nargs="?", const="", metavar="EXTRA",
                       help="transcribe every selected page's text verbatim")
    parser.add_argument("--dpi", type=int, default=100,
                        help="render resolution in dots per inch (default: 100)")
    parser.add_argument("--keep", type=Path,
                        help="keep rendered page PNGs in this directory instead of a temporary one")
    args = parser.parse_args()
    if not 1 <= args.dpi <= 600:
        parser.exit(2, f"pdf_pages: --dpi must be between 1 and 600\n")
    try:
        pdftoppm, pdfinfo = require_poppler()
        glance = require_glance()
        pdf = args.pdf.expanduser()
        if not pdf.is_file():
            raise ScriptError(f"PDF not found: {pdf}")
        total = pdf_page_count(pdf, pdfinfo)
        pages = parse_page_spec(args.pages, total)
        if not pages:
            raise ScriptError(f"PDF has no pages to process: {pdf}")
        mode = "ocr" if args.ocr is not None else ("query" if args.query else "describe")
        with ExitStack() as stack:
            if args.keep:
                keep_base = Path(args.keep).expanduser()
                try:
                    keep_base.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise ScriptError(f"Cannot use --keep directory {keep_base}: {exc}") from exc
                # A fresh subdirectory per run keeps stale renders from an
                # earlier PDF out of this run's page glob; exist_ok=False
                # makes that uniqueness a hard guarantee.
                stamp = f"{pdf.stem}-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000:06d}"
                try:
                    for attempt in range(3):
                        out_dir = keep_base / (stamp if attempt == 0 else f"{stamp}-{attempt}")
                        try:
                            out_dir.mkdir()
                        except FileExistsError:
                            continue
                        break
                    else:
                        raise ScriptError(
                            f"Cannot create a fresh --keep subdirectory under {keep_base} "
                            f"(names {stamp}, {stamp}-1, {stamp}-2 all exist)"
                        )
                except OSError as exc:
                    raise ScriptError(f"Cannot use --keep directory {keep_base}: {exc}") from exc
            else:
                out_dir = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="pdf_pages-")))
            images = render_pages(pdf, pages, args.dpi, out_dir, pdftoppm)
            if args.keep:
                print(f"Rendered pages kept in {out_dir}", file=sys.stderr)
            print(describe_pages(images, pages, total, mode, args.query, args.ocr, glance))
    except ScriptError as exc:
        parser.exit(1, f"pdf_pages: {exc}\n")


if __name__ == "__main__":
    main()
