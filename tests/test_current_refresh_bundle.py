"""Current refresh bundle — verify atomicity of Output/current artifacts.

The "current refresh bundle" is the set of scripts that write into
Output/current/ and Output/judgment/.  After any refresh, these files
must share the same date — they cannot drift independently.

Bundle scripts:
  bridge_replay_to_current.py      → framework_output.json
  quality_field_validator.py       → quality_validation.json
  judgment_layer.py                → judgment/latest.json
  judgment_promotion_gate.py       → judgment/promotion_gate.json
  build_next_actions.py            → NEXT_ACTIONS.md
  build_current_status.py          → status.json
  build_readme_first.py            → 00_READ_ME_FIRST.md

Invariant:
  All bundle artifacts must have the same date (within 1 day tolerance
  for cross-midnight runs).  If any file is >1 day older than the
  newest, the bundle is not atomic — something was refreshed alone.

See: governance/daily_pipeline_registry.yaml
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURRENT = ROOT / "Output" / "current"
JUDGMENT = ROOT / "Output" / "judgment"

# ---------------------------------------------------------------------------
# Bundle artifact definitions
# ---------------------------------------------------------------------------

BUNDLE_ARTIFACTS: list[tuple[str, Path, str]] = [
    # (label, path, date_field)
    ("framework_output", CURRENT / "framework_output.json", "as_of"),
    ("status", CURRENT / "status.json", "date"),
    ("quality_validation", CURRENT / "quality_validation.json", "as_of"),
    ("judgment", JUDGMENT / "latest.json", "as_of"),
]


def _extract_date(path: Path, field: str) -> str | None:
    """Extract YYYY-MM-DD from a JSON file's date field."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get(field, "")
        if not raw:
            return None
        return raw[:10]  # Normalize to date-only
    except Exception:
        return None


def _extract_mtime_date(path: Path) -> str | None:
    """Extract YYYY-MM-DD from file modification time."""
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_bundle_artifacts_exist() -> None:
    """All bundle artifacts must exist on disk."""
    missing = []
    for label, path, _ in BUNDLE_ARTIFACTS:
        if not path.exists():
            missing.append(label)
    assert not missing, f"Bundle artifacts missing: {missing}"


def test_bundle_dates_consistent() -> None:
    """All bundle artifacts must have the same date (1-day tolerance)."""
    dates: dict[str, str] = {}
    for label, path, field in BUNDLE_ARTIFACTS:
        d = _extract_date(path, field)
        if d:
            dates[label] = d

    if len(dates) < 2:
        pytest.skip("Not enough dated artifacts to compare")

    # Parse all dates and check max delta
    parsed = {k: datetime.strptime(v, "%Y-%m-%d") for k, v in dates.items()}
    newest = max(parsed.values())
    stale = {}
    for label, dt in parsed.items():
        delta = (newest - dt).days
        if delta > 1:
            stale[label] = f"{dates[label]} ({delta} days behind)"

    assert not stale, (
        "Bundle artifacts are not date-consistent:\n"
        + "\n".join(f"  {k}: {v}" for k, v in stale.items())
        + f"\n  newest: {newest.strftime('%Y-%m-%d')}"
    )


def test_bundle_dates_match_judgment() -> None:
    """status.json date must match judgment as_of (same pipeline run)."""
    status_d = _extract_date(CURRENT / "status.json", "date")
    judgment_d = _extract_date(JUDGMENT / "latest.json", "as_of")
    if not status_d or not judgment_d:
        pytest.skip("Missing status or judgment date")
    assert status_d == judgment_d, (
        f"Bundle mismatch: status={status_d}, judgment={judgment_d}"
    )


def test_readme_first_mtime_matches_bundle() -> None:
    """00_READ_ME_FIRST.md mtime should be same day as bundle artifacts."""
    readme = CURRENT / "00_READ_ME_FIRST.md"
    if not readme.exists():
        pytest.skip("00_READ_ME_FIRST.md not found")

    readme_date = _extract_mtime_date(readme)
    generated_date = _extract_date(CURRENT / "status.json", "generated_at")
    if not readme_date or not generated_date:
        pytest.skip("Missing dates")

    assert readme_date == generated_date, (
        f"README mtime={readme_date} != status generated_at={generated_date} — "
        f"README was not regenerated with the last bundle refresh"
    )


def test_bundle_no_na_placeholders() -> None:
    """Bundle artifacts should not contain N/A in value positions."""
    na_found = []
    for label, path, _ in BUNDLE_ARTIFACTS:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(data)
            # Check for N/A in string values (not in keys)
            if '"N/A"' in text:
                na_found.append(label)
        except Exception:
            pass
    assert not na_found, (
        f"Bundle artifacts contain N/A values: {na_found}"
    )


def test_bundle_gate_status_consistent() -> None:
    """quality_validation gate in status.json must match judgment gate_status."""
    try:
        status = json.loads((CURRENT / "status.json").read_text(encoding="utf-8"))
        judgment = json.loads((JUDGMENT / "latest.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        pytest.skip("Missing status or judgment file")

    s_quality = status.get("promotion_gate", {}).get("blocked_gates", [])
    j_quality = judgment.get("gate_status", {}).get("quality_validation", "")

    if not j_quality:
        pytest.skip("Missing quality_validation in judgment gate_status")

    # If quality_validation is FAIL, caselab should be in blocked_gates
    if j_quality == "FAIL":
        assert "caselab" in s_quality or "quality" in str(s_quality).lower(), (
            f"quality_validation=FAIL in judgment but not blocked in status: "
            f"blocked_gates={s_quality}"
        )
