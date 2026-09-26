"""Current artifact semantic chain — verify outputs explain each other.

Hermetic mode (default everywhere):
  Reads committed fixtures under tests/fixtures/current_chain/.

Operator mode:
  Set SYSTEM_TEST_USE_LIVE_ARTIFACTS=1 explicitly. Live operator checks belong
  in test_current_artifact_chain_operator.py and are excluded from merge
  evidence on clean checkouts.

See: governance/daily_pipeline_registry.yaml
     governance/runtime_status_contract.yaml
     governance/architecture_cleanup_decisions.md D2
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from verity.runtime._runtime_status_contract import (
    framework_output_status_values,
    judgment_confidence_values,
    judgment_decision_values,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "current_chain"


def _prefer_live() -> bool:
    return os.environ.get("SYSTEM_TEST_USE_LIVE_ARTIFACTS") == "1"


def _base() -> Path:
    return ROOT / "Output" / "current" if _prefer_live() else FIXTURE_ROOT


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _artifact(name: str) -> Path:
    return _base() / name


@pytest.fixture()
def framework_output() -> dict:
    p = _artifact("framework_output.json")
    if not p.exists():
        pytest.skip("framework_output.json not found")
    return _load_json(p)


@pytest.fixture()
def status_json() -> dict:
    p = _artifact("status.json")
    if not p.exists():
        pytest.skip("status.json not found")
    return _load_json(p)


@pytest.fixture()
def quality_validation() -> dict:
    p = _artifact("quality_validation.json")
    if not p.exists():
        pytest.skip("quality_validation.json not found")
    return _load_json(p)


@pytest.fixture()
def judgment() -> dict:
    if _prefer_live():
        p = ROOT / "Output" / "judgment" / "latest.json"
    else:
        p = FIXTURE_ROOT / "judgment" / "latest.json"
    if not p.exists():
        pytest.skip("judgment/latest.json not found")
    return _load_json(p)


@pytest.fixture()
def readme_first() -> str:
    p = _artifact("00_READ_ME_FIRST.md")
    if not p.exists():
        pytest.skip("00_READ_ME_FIRST.md not found")
    return p.read_text(encoding="utf-8")


def test_framework_output_has_required_keys(framework_output: dict) -> None:
    required = {"schema_version", "framework_id", "as_of", "status"}
    missing = required - set(framework_output.keys())
    assert not missing, f"framework_output.json missing keys: {missing}"


def test_framework_output_status_is_known(framework_output: dict) -> None:
    valid = framework_output_status_values(include_legacy=True)
    status = framework_output.get("status", "")
    assert status in valid, f"Unknown framework status: {status!r}"


def test_framework_output_as_of_is_recent(framework_output: dict) -> None:
    """as_of should be within the last 7 days — catches stale operator artifacts."""
    if not _prefer_live():
        pytest.skip("fixture as_of is pinned; freshness applies to operator artifacts")
    as_of = framework_output.get("as_of", "")
    if not as_of:
        pytest.skip("no as_of in framework_output")
    try:
        dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.strptime(as_of, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    assert age.days <= 7, f"framework_output as_of is {age.days} days old: {as_of}"


def test_status_has_judgment_section(status_json: dict) -> None:
    assert "judgment" in status_json, "status.json missing 'judgment' section"
    j = status_json["judgment"]
    assert "decision" in j, "status.judgment missing 'decision'"
    assert "confidence" in j, "status.judgment missing 'confidence'"


def test_status_promotion_gate_consistent(status_json: dict) -> None:
    """If promotion gate is BLOCKED, must have blocked_gates listed."""
    pg = status_json.get("promotion_gate", {})
    if pg.get("status") == "BLOCKED":
        assert pg.get("blocked_gates"), (
            "promotion_gate status=BLOCKED but no blocked_gates listed"
        )


def test_status_date_matches_framework(status_json: dict, framework_output: dict) -> None:
    """status.json date should match framework_output as_of date."""
    s_date = status_json.get("date", "")[:10]
    f_date = framework_output.get("as_of", "")[:10]
    if not s_date or not f_date:
        pytest.skip("missing date fields")
    assert s_date == f_date, (
        f"Date mismatch: status.json={s_date}, framework_output={f_date}"
    )


def test_quality_has_gate_summary(quality_validation: dict) -> None:
    assert "gate_summary" in quality_validation, "quality_validation missing gate_summary"
    gs = quality_validation["gate_summary"]
    expected_gates = {"K_gate", "X_gate", "caselab_gate", "hmm_gate"}
    missing = expected_gates - set(gs.keys())
    assert not missing, f"gate_summary missing gates: {missing}"


def test_quality_gate_values_valid(quality_validation: dict) -> None:
    valid = {"PASS", "FAIL", "SKIP", "WARN", "NOT_EVALUATED"}
    gs = quality_validation.get("gate_summary", {})
    bad = {k: v for k, v in gs.items() if v not in valid}
    assert not bad, f"Invalid gate values: {bad}"


def test_quality_fail_has_issues(quality_validation: dict) -> None:
    """If status is FAIL, error_count should be > 0 and issues should be non-empty."""
    if quality_validation.get("status") == "FAIL":
        assert quality_validation.get("error_count", 0) > 0, (
            "status=FAIL but error_count is 0"
        )
        assert quality_validation.get("issues"), "status=FAIL but issues list is empty"


def test_judgment_has_required_keys(judgment: dict) -> None:
    required = {"decision", "confidence", "claim_ceiling"}
    missing = required - set(judgment.keys())
    assert not missing, f"judgment missing keys: {missing}"


def test_judgment_decision_is_known(judgment: dict) -> None:
    valid = judgment_decision_values(include_legacy=True)
    decision = judgment.get("decision", "")
    assert decision in valid, f"Unknown judgment decision: {decision!r}"


def test_judgment_confidence_is_known(judgment: dict) -> None:
    valid = judgment_confidence_values()
    conf = judgment.get("confidence", "")
    if isinstance(conf, dict):
        conf = conf.get("level", "")
    assert conf in valid, f"Unknown confidence: {conf!r}"


def test_judgment_gate_status_present(judgment: dict) -> None:
    if not _prefer_live() and "gate_status" not in judgment:
        pytest.skip("fixture judgment omits gate_status; required on operator artifacts")
    assert "gate_status" in judgment, "judgment missing gate_status"


def test_judgment_consistent_with_status(
    judgment: dict, status_json: dict
) -> None:
    """judgment.latest.json decision should match status.json judgment.decision."""
    j_dec = judgment.get("decision", "")
    s_dec = status_json.get("judgment", {}).get("decision", "")
    if not j_dec or not s_dec:
        pytest.skip("missing decision in one file")
    assert j_dec == s_dec, (
        f"Decision mismatch: judgment={j_dec}, status={s_dec}"
    )


def test_judgment_inputs_reference_known_artifacts(judgment: dict) -> None:
    """judgment.inputs should reference framework_output and/or status."""
    inputs = judgment.get("inputs", {})
    if not inputs:
        pytest.skip("no inputs in judgment")
    input_str = json.dumps(inputs)
    assert "neutral_pressure_snapshot" in input_str or "status" in input_str, (
        "judgment.inputs doesn't reference neutral_pressure_snapshot or status"
    )


def test_readme_first_no_na(readme_first: str) -> None:
    """READ_ME_FIRST should not contain N/A placeholders."""
    lines = readme_first.splitlines()
    na_lines = [
        line.strip()
        for line in lines
        if "N/A" in line and not line.strip().startswith("#")
    ]
    assert not na_lines, (
        "READ_ME_FIRST contains N/A placeholders:\n" + "\n".join(na_lines[:5])
    )


def test_readme_first_no_stale_authority(readme_first: str) -> None:
    """READ_ME_FIRST should not be an empty stub."""
    min_len = 40 if not _prefer_live() else 100
    assert len(readme_first) > min_len, (
        f"READ_ME_FIRST looks like a stub (< {min_len} chars)"
    )


def test_artifacts_not_stale_relative_to_each_other(
    framework_output: dict,
    status_json: dict,
    judgment: dict,
) -> None:
    """Key artifacts should be from the same run (same date)."""
    dates = set()
    for d, _label in [
        (framework_output.get("as_of"), "framework_output"),
        (status_json.get("date"), "status.json"),
        (judgment.get("as_of"), "judgment"),
    ]:
        if d:
            dates.add(d[:10])
    if len(dates) > 1:
        pytest.fail(
            f"Artifacts from different dates — likely stale mix: {dates}"
        )
