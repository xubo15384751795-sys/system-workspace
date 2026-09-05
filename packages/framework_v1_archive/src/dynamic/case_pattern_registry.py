"""Load declarative case pattern YAMLs (configuration; not market data)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

_CASE_PATTERN_DIR = Path(__file__).resolve().parent / "case_patterns"
_REGISTERED_IDS = (
    "ldi_2022",
    "svb_2023",
    "ltcm_1998",
    "archegos_2021",
    "chf_peg_2015",
    "repo_spike_2019",
)


def load_case_pattern(case_id: str) -> dict[str, Any]:
    """Load the YAML pattern for case_id and return it as a plain dict."""
    path = _CASE_PATTERN_DIR / f"{case_id}.yaml"
    if not path.is_file():
        known = ", ".join(repr(k) for k in list_case_patterns()) or "(none)"
        raise FileNotFoundError(f"No case pattern file for {case_id!r} at {path}. Known: {known}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Case pattern {case_id!r} must be a mapping at the top level")
    return cast(dict[str, Any], raw)


def list_case_patterns() -> list[str]:
    """Return registered case_id values (sorted)."""
    return sorted(_REGISTERED_IDS)


def get_recommended_signal_cards(case_id: str) -> list[str]:
    data = load_case_pattern(case_id)
    cards = data.get("recommended_signal_cards")
    if not isinstance(cards, list) or not all(isinstance(x, str) for x in cards):
        raise ValueError(f"recommended_signal_cards must be a list[str] in {case_id!r}")
    return list(cards)


def get_known_failure_modes(case_id: str) -> list[str]:
    data = load_case_pattern(case_id)
    modes = data.get("known_failure_modes")
    if not isinstance(modes, list) or not all(isinstance(x, str) for x in modes):
        raise ValueError(f"known_failure_modes must be a list[str] in {case_id!r}")
    return list(modes)
