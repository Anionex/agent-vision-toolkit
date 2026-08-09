#!/usr/bin/env python3
"""Dispatch Reasonix skill calls to the repository's existing vision CLIs."""

from pathlib import Path
import os
import shutil
import sys


ENTRY_POINTS = {
    "crop": "bin/crop",
    "detect": "bin/detect",
    "dominant-colors": "skills/vision-tools/scripts/dominant_colors.py",
    "extract-fg": "skills/vision-tools/scripts/extract_fg.py",
    "glance": "bin/glance",
    "ground": "bin/ground",
    "html-shot": "skills/vision-tools/scripts/html_shot.py",
    "long-screenshot-ocr": "skills/vision-tools/scripts/long_screenshot_ocr.py",
    "pixel-diff": "skills/vision-tools/scripts/pixel_diff.py",
    "trace": "bin/trace",
}


def toolkit_root(glance_path=None, cwd=None):
    """Find the toolkit checkout selected by PATH or the current workspace."""
    roots = []
    selected_glance = glance_path or shutil.which("glance")
    if selected_glance:
        roots.extend(Path(selected_glance).expanduser().resolve().parents)

    current = Path.cwd() if cwd is None else Path(cwd)
    current = current.expanduser().resolve()
    roots.extend((current, *current.parents))

    seen = set()
    for candidate in roots:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if (candidate / "vision_client.py").is_file() and (candidate / "bin" / "glance").is_file():
            return candidate
    raise RuntimeError(
        "agent-vision-toolkit CLI checkout not found; add its bin directory to PATH"
    )


def normalize_tool(name):
    return name.strip().lower().replace("_", "-")


def resolve_target(name, glance_path=None, cwd=None):
    tool = normalize_tool(name)
    relative = ENTRY_POINTS.get(tool)
    if relative is None:
        raise KeyError(tool)
    target = toolkit_root(glance_path=glance_path, cwd=cwd) / relative
    if not target.is_file():
        raise RuntimeError(f"toolkit entry point is missing: {relative}")
    return target


def print_usage(stream):
    tools = ", ".join(sorted(ENTRY_POINTS))
    print("usage: vision_cli.py <tool> [tool arguments] | --list | --check", file=stream)
    print(f"tools: {tools}", file=stream)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--list"]:
        print("\n".join(sorted(ENTRY_POINTS)))
        return 0
    if args == ["--check"]:
        try:
            root = toolkit_root()
            for tool in ENTRY_POINTS:
                resolve_target(tool)
        except RuntimeError as exc:
            print(f"vision toolkit error: {exc}", file=sys.stderr)
            return 1
        print(root)
        return 0
    if not args or args[0] in {"-h", "--help"}:
        print_usage(sys.stdout if args else sys.stderr)
        return 0 if args else 2

    tool = normalize_tool(args.pop(0))
    try:
        target = resolve_target(tool)
    except KeyError:
        print(f"unknown vision tool: {tool}", file=sys.stderr)
        print_usage(sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"vision toolkit error: {exc}", file=sys.stderr)
        return 1

    try:
        os.execv(sys.executable, [sys.executable, str(target), *args])
    except OSError as exc:
        print(f"vision toolkit error: cannot run {target}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
