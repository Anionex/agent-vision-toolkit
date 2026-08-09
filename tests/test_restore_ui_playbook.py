#!/usr/bin/env python3
"""Contract checks for the shipped fast UI restore workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PLAYBOOK = ROOT / "skills" / "vision-tools" / "references" / "restore-ui.md"
SKILL = ROOT / "skills" / "vision-tools" / "SKILL.md"


def fast_mode_section() -> str:
    text = PLAYBOOK.read_text(encoding="utf-8")
    start = text.index("## Fast restore mode")
    end = text.index("## Standard restore workflow")
    return text[start:end]


def test_fast_mode_contract() -> None:
    section = fast_mode_section()
    normalized = " ".join(section.split())

    required_phrases = (
        "about three minutes",
        "one full-image `detect` pass",
        "six combined image-inspection calls",
        "`view_image`",
        "`glance`",
        "Count every call whether it is serial or parallel",
        "icon library contains a reasonably similar",
        "visually similar CSS values",
        "Deliver the screenshot",
    )
    missing = [phrase for phrase in required_phrases if phrase not in normalized]
    assert not missing, f"fast restore contract is missing: {missing}"


def test_fast_mode_is_discoverable() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "three-minute fast approximation mode" in text


if __name__ == "__main__":
    test_fast_mode_contract()
    test_fast_mode_is_discoverable()
    print("PASS: fast UI restore workflow keeps its time, fidelity, and call budgets")
