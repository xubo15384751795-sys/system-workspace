"""Verify verify_experiment_core_judgment detects and classifies experimental leaks."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_experiment_core_judgment import (
    _classify_field,
    _is_expired,
    classify_reference,
    get_experimental_modules,
    verify_core_judgment,
)


def test_get_experimental_modules():
    """Extracts REAL_EXPERIMENTAL module names from registry."""
    registry = {
        "workbench": {"status": "CANONICAL"},
        "ml_signals": {"status": "REAL_EXPERIMENTAL"},
        "backtest_lens": {"status": "REAL_EXPERIMENTAL"},
        "harvester": {"status": "CANONICAL"},
    }
    result = get_experimental_modules(registry)
    assert "ml_signals" in result
    assert "backtest_lens" in result
    assert len(result) == 2


def test_get_experimental_modules_empty():
    """Returns empty when no experimental modules."""
    registry = {
        "workbench": {"status": "CANONICAL"},
        "harvester": {"status": "CANONICAL"},
    }
    assert get_experimental_modules(registry) == []


def test_classify_field_decision():
    """Decision fields are classified as 'decision'."""
    assert _classify_field("decision") == "decision"
    assert _classify_field("trade_decision") == "decision"
    assert _classify_field("risk_gate") == "decision"
    assert _classify_field("position_sizing") == "decision"


def test_classify_field_confidence():
    """Confidence fields are classified as 'confidence'."""
    assert _classify_field("confidence") == "confidence"
    assert _classify_field("claim_ceiling") == "confidence"
    assert _classify_field("next_action") == "confidence"


def test_classify_field_diagnostic():
    """Diagnostic/provenance fields are classified as 'diagnostic'."""
    assert _classify_field("inputs.hmm") == "diagnostic"
    assert _classify_field("signals[1].source") == "diagnostic"
    assert _classify_field("metadata.generated_at") == "diagnostic"
    assert _classify_field("provenance.source") == "diagnostic"


def test_classify_reference_in_decision_field_is_block():
    """Experimental reference in decision field → block."""
    result = classify_reference(Path("test.json"), "ml_signals", "decision")
    assert result["classification"] == "block"
    assert result["decision"] == "FAIL"
    assert result["affects_core_judgment"] is True


def test_classify_reference_in_confidence_field_requires_bridge():
    """Experimental reference in confidence field without marker → require_bridge."""
    filepath = ROOT / "Output" / "judgment" / "test_fixture.json"
    result = classify_reference(filepath, "ml_signals", "confidence")
    assert result["classification"] == "require_bridge"
    assert result["decision"] == "FAIL"
    assert result["affects_core_judgment"] is True


def test_classify_reference_diagnostic_without_marker_is_unknown():
    """Experimental reference in diagnostic field without marker → unknown."""
    filepath = ROOT / "Output" / "judgment" / "test_fixture.json"
    result = classify_reference(filepath, "ml_signals", "some_other_field")
    assert result["classification"] == "unknown"
    assert result["decision"] == "FAIL"


def test_is_expired_no_date():
    """Marker with no expiry is treated as expired."""
    assert _is_expired({}) is True
    assert _is_expired({"expires_at": None}) is True


def test_is_expired_past_date():
    """Marker with past expiry is expired."""
    assert _is_expired({"expires_at": "2020-01-01"}) is True


def test_verify_returns_empty_when_no_experimental():
    """No violations when registry has no experimental modules."""
    mock_registry = {"workbench": {"status": "CANONICAL"}}
    with (
        patch("verify_experiment_core_judgment.load_yaml", return_value=mock_registry),
        patch("verify_experiment_core_judgment.scan_core_judgment_paths", return_value=[]),
    ):
        violations, entries = verify_core_judgment(ROOT)
        assert violations == []
        assert entries == []


def test_verify_returns_empty_when_no_core_dirs():
    """No violations when core judgment directories don't exist."""
    mock_registry = {"ml_signals": {"status": "REAL_EXPERIMENTAL"}}
    with (
        patch("verify_experiment_core_judgment.load_yaml", return_value=mock_registry),
        patch("verify_experiment_core_judgment.scan_core_judgment_paths", return_value=[]),
    ):
        violations, entries = verify_core_judgment(ROOT)
        assert violations == []
        assert entries == []


def test_approved_marker_allows_diagnostic():
    """Approved diagnostic marker with valid expiry → PASS."""
    import json as json_mod
    import tempfile

    # Create a mock judgment file under Output/judgment/ so relative_to(ROOT) works
    judgment_dir = ROOT / "Output" / "judgment"
    judgment_dir.mkdir(parents=True, exist_ok=True)
    data = {"inputs": {"hmm": "/path/to/ml_signals/latest/regime_hmm.json"}, "decision": "WATCH"}
    filepath = judgment_dir / "_test_fixture.json"
    filepath.write_text(json_mod.dumps(data))

    try:
        # The approved marker for Output/judgment/*.json + inputs.hmm should match
        result = classify_reference(filepath, "ml_signals", "inputs.hmm")

        assert result["classification"] == "allow_diagnostic"
        assert result["decision"] == "PASS"
        assert result["affects_core_judgment"] is False
    finally:
        filepath.unlink(missing_ok=True)
