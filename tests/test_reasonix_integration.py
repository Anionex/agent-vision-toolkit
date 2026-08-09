#!/usr/bin/env python3
"""Unit and smoke tests for the Reasonix Skill + CLI integration."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "integrations" / "reasonix"
MANIFEST = PLUGIN_ROOT / "reasonix-plugin.json"
SKILL = PLUGIN_ROOT / "skills" / "vision-tools" / "SKILL.md"
DISPATCHER = SKILL.parent / "scripts" / "vision_cli.py"


def load_dispatcher():
    spec = importlib.util.spec_from_file_location("reasonix_vision_cli", DISPATCHER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["apiVersion"] == "reasonix.io/plugin/v1"
    assert manifest["name"] == "agent-vision-toolkit"
    assert manifest["version"] == "0.1.0"
    assert set(manifest["contributes"]) == {"skills"}
    assert manifest["contributes"]["skills"] == ["skills"]
    assert "runtime" not in manifest
    assert "mcpServers" not in manifest
    assert "mcpServers" not in manifest["contributes"]
    assert not (ROOT / "reasonix-plugin.json").exists()


def test_compact_plugin_package():
    package_bytes = sum(path.stat().st_size for path in PLUGIN_ROOT.rglob("*") if path.is_file())
    assert package_bytes < 1_000_000
    assert not (PLUGIN_ROOT / "vision_client.py").exists()
    assert not (PLUGIN_ROOT / "bin").exists()


def test_thin_skill_shape():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\nname: vision-tools\n")
    assert "vision_cli.py" in text
    assert "not a second copy of the toolkit" in text
    assert not (SKILL.parent / "references").exists()
    assert len(text.encode("utf-8")) < 10_000


def test_dispatcher_resolution():
    module = load_dispatcher()
    glance = ROOT / "bin" / "glance"
    assert module.toolkit_root(glance_path=glance, cwd=PLUGIN_ROOT) == ROOT
    assert module.resolve_target("glance", glance_path=glance) == ROOT / "bin" / "glance"
    assert module.resolve_target("long_screenshot_ocr", glance_path=glance) == (
        ROOT / "skills" / "vision-tools" / "scripts" / "long_screenshot_ocr.py"
    )
    for tool in module.ENTRY_POINTS:
        assert module.resolve_target(tool, glance_path=glance).is_file()


def test_dispatcher_cli():
    env = dict(os.environ)
    env["PATH"] = str(ROOT / "bin") + os.pathsep + env.get("PATH", "")

    listed = subprocess.run(
        [sys.executable, str(DISPATCHER), "--list"],
        text=True,
        capture_output=True,
        check=True,
    )
    names = set(listed.stdout.splitlines())
    assert {"glance", "ground", "detect", "trace", "crop"}.issubset(names)

    checked = subprocess.run(
        [sys.executable, str(DISPATCHER), "--check"],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )
    assert Path(checked.stdout.strip()).resolve() == ROOT

    for tool in ("glance", "ground", "detect", "trace", "crop"):
        help_result = subprocess.run(
            [sys.executable, str(DISPATCHER), tool, "--help"],
            text=True,
            capture_output=True,
            check=True,
            env=env,
        )
        assert "usage:" in help_result.stdout.lower()

    unknown = subprocess.run(
        [sys.executable, str(DISPATCHER), "not-a-tool"],
        text=True,
        capture_output=True,
    )
    assert unknown.returncode == 2
    assert "unknown vision tool" in unknown.stderr

    with tempfile.TemporaryDirectory() as empty_cwd:
        missing_env = dict(os.environ)
        missing_env["PATH"] = ""
        missing = subprocess.run(
            [sys.executable, str(DISPATCHER), "glance", "--help"],
            text=True,
            capture_output=True,
            cwd=empty_cwd,
            env=missing_env,
        )
    assert missing.returncode == 1
    assert "add its bin directory to PATH" in missing.stderr


def main():
    test_manifest()
    test_compact_plugin_package()
    test_thin_skill_shape()
    test_dispatcher_resolution()
    test_dispatcher_cli()
    print("REASONIX INTEGRATION TEST PASS")


if __name__ == "__main__":
    main()
