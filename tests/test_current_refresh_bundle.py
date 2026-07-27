"""Current refresh bundle — verify atomicity of Output/current artifacts.

Hermetic: uses sandbox workspace seeded from tests/fixtures/current_chain.
Does not touch operator Output/.

See: governance/daily_pipeline_registry.yaml
     SYSTEM_LARGE_SCALE_VALIDATION_ROADMAP.md P0-2
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.helpers.sandbox_workspace import build_sandbox_workspace


@pytest.fixture()
def current(tmp_path: Path) -> Path:
    sandbox = build_sandbox_workspace(tmp_path / "workspace")
    return sandbox / "Output" / "current"


@pytest.fixture()
def judgment(current: Path) -> Path:
    return current.parent / "judgment"


def _bundle_paths(current: Path, judgment: Path) -> list[tuple[str, Path, str]]:
    return [
        ("framework_output", current / "framework_output.json", "as_of"),
        ("status", current / "status.json", "date"),
        ("quality_validation", current / "quality_validation.json", "as_of"),
        ("judgment", judgment / "latest.json", "as_of"),
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
        return raw[:10]
    except Exception:
        return None


def _extract_mtime_date(path: Path) -> str | None:
    if not path.exists():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime.strftime("%Y-%m-%d")


def test_bundle_artifacts_exist(current: Path, judgment: Path) -> None:
    missing = [label for label, path, _ in _bundle_paths(current, judgment) if not path.exists()]
    assert not missing, f"Bundle artifacts missing: {missing}"


def test_bundle_dates_consistent(current: Path, judgment: Path) -> None:
    dates: dict[str, str] = {}
    for label, path, field in _bundle_paths(current, judgment):
        d = _extract_date(path, field)
        if d:
            dates[label] = d

    assert len(dates) >= 2, f"Not enough dated artifacts to compare: {dates}"

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


def test_bundle_dates_match_judgment(current: Path, judgment: Path) -> None:
    status_d = _extract_date(current / "status.json", "date")
    judgment_d = _extract_date(judgment / "latest.json", "as_of")
    assert status_d and judgment_d
    assert status_d == judgment_d, f"Bundle mismatch: status={status_d}, judgment={judgment_d}"


def test_readme_first_mtime_matches_bundle(current: Path) -> None:
    readme = current / "00_READ_ME_FIRST.md"
    assert readme.exists()
    readme_date = _extract_mtime_date(readme)
    generated_date = _extract_date(current / "status.json", "generated_at")
    assert readme_date and generated_date
    assert readme_date == generated_date, (
        f"README mtime={readme_date} != status generated_at={generated_date}"
    )


def test_bundle_no_na_placeholders(current: Path, judgment: Path) -> None:
    na_found = []
    for label, path, _ in _bundle_paths(current, judgment):
        data = json.loads(path.read_text(encoding="utf-8"))
        if '"N/A"' in json.dumps(data):
            na_found.append(label)
    assert not na_found, f"Bundle artifacts contain N/A values: {na_found}"


def test_bundle_gate_status_consistent(current: Path, judgment: Path) -> None:
    status = json.loads((current / "status.json").read_text(encoding="utf-8"))
    judgment_data = json.loads((judgment / "latest.json").read_text(encoding="utf-8"))

    s_quality = status.get("promotion_gate", {}).get("blocked_gates", [])
    j_quality = judgment_data.get("gate_status", {}).get("quality_validation", "")
    assert j_quality, "fixture judgment must include gate_status.quality_validation"

    if j_quality == "FAIL":
        assert "caselab" in s_quality or "quality" in str(s_quality).lower(), (
            f"quality_validation=FAIL in judgment but not blocked in status: "
            f"blocked_gates={s_quality}"
        )
