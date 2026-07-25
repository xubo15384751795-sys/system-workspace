"""WB-G1/B2: Jargon lint on the home-page first screen (constitution enforcement).

PRODUCT_FRAMEWORK_BOUNDARY.md: "Product tools must not require framework
concepts for basic use." The first screen (title + Plain Summary) must be
readable by someone who does not know the framework. Internal jargon is
allowed only in the advanced sections (System Status and below).

This test is the executable enforcement of that clause: if anyone edits the
home page to push framework jargon into the first screen, CI goes red.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "Output" / "current" / "00_READ_ME_FIRST.md"

# Forbidden jargon on the first screen (Plain Summary). These are framework-
# internal terms that a non-framework reader cannot interpret. The internal
# state label in parentheses (e.g. "(internal: RISK_ON, regime ...)") is
# allowed because it is clearly bracketed as a translation aid, not the
# primary message.
FORBIDDEN_JARGON = [
    "FULL_PROXY_REDUCED",
    "RESEARCH_REVIEW",
    "promotion gate",
    "promotion_gate",
    "morphology",
    "structural_diagnostic",
    "claim_ceiling",
    "effective_size",
    "velocity_gate",
    "MIXED_ANCHOR_PATH_STRESS",
    "stress_relief",
    "structural_replay",
    "deformation",
    "kalman",
    "absorption_capacity",
    "lambda_max",
    "shadow_mass",
]


@pytest.fixture()
def readme_text() -> str:
    if not README.exists():
        pytest.skip("00_READ_ME_FIRST.md not found")
    return README.read_text(encoding="utf-8")


def _first_screen(text: str) -> str:
    """Return the title + Plain Summary section (everything before System Status)."""
    parts = text.split("## System Status")
    return parts[0] if parts else text


def test_first_screen_has_plain_summary(readme_text: str) -> None:
    """WB-B1: the first screen must contain a Plain Summary section."""
    screen = _first_screen(readme_text)
    assert "## Plain Summary" in screen, (
        "Plain Summary section missing from first screen. The home page must "
        "lead with a plain-language summary (constitution: basic layer must "
        "not require framework concepts)."
    )


def test_first_screen_answers_three_questions(readme_text: str) -> None:
    """WB-B1: Plain Summary must answer what-state / changed / what-would-change."""
    screen = _first_screen(readme_text)
    # The three plain-language questions
    assert re.search(r"\*\*Today", screen, re.IGNORECASE), (
        "Plain Summary missing 'Today' (what is the current state)"
    )
    assert re.search(r"\*\*Compared to yesterday", screen, re.IGNORECASE), (
        "Plain Summary missing 'Compared to yesterday' (did it change)"
    )
    assert re.search(r"\*\*What would change the decision", screen, re.IGNORECASE), (
        "Plain Summary missing 'What would change the decision' (invalidation)"
    )


def test_first_screen_no_jargon(readme_text: str) -> None:
    """WB-G1/B2: no framework jargon on the first screen (outside parentheticals).

    The constitution forbids framework concepts in the basic layer. The first
    screen (title + Plain Summary) must be readable without framework
    knowledge. Internal labels are allowed only inside parenthetical
    "(internal: ...)" translation aids.
    """
    screen = _first_screen(readme_text)
    # Strip parenthetical "(internal: ...)" aids before linting, since those
    # are explicitly translation aids, not the primary message.
    screen_linted = re.sub(r"\(internal:[^)]*\)", "", screen, flags=re.IGNORECASE)

    violations = []
    for term in FORBIDDEN_JARGON:
        if re.search(re.escape(term), screen_linted, re.IGNORECASE):
            violations.append(term)

    assert not violations, (
        f"Framework jargon found on the first screen (constitution violation): "
        f"{violations}. The basic layer must not require framework concepts. "
        f"Move these terms to the advanced sections (System Status and below) "
        f"or wrap them in an '(internal: ...)' translation aid."
    )
