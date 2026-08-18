from __future__ import annotations

import logging

import pytest
from system_learning.ml_integrity import constitution, pollution_monitor


def test_rule_evaluation_error_is_not_treated_as_compliance(caplog) -> None:
    rule = constitution.Rule(
        id="TEST-RULE",
        severity=constitution.Severity.RED,
        short="test rule",
        description="test",
        check=lambda _evidence: 1 / 0,
    )
    caplog.set_level(logging.ERROR, logger=constitution.__name__)

    with pytest.raises(
        constitution.ConstitutionEvaluationError,
        match="TEST-RULE.*signal use is blocked",
    ):
        rule.evaluate({})

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "rule_id=TEST-RULE" in messages
    assert "ZeroDivisionError" in messages


def test_pollution_monitor_reports_failed_constitution_evaluation(tmp_path, monkeypatch) -> None:
    def fail_closed(*_args, **_kwargs):
        raise constitution.ConstitutionEvaluationError("bounded test failure")

    monkeypatch.setattr(pollution_monitor, "enforce", fail_closed)

    report = pollution_monitor.run_pollution_check(
        signals_root=tmp_path / "signals",
        runs_root=tmp_path / "runs",
        events_dir=tmp_path / "events",
    )

    assert report.passed is False
    assert report.red_violations == []
    assert "constitution evaluation failed; signal use is blocked" in report.notes
    summary = next((tmp_path / "events").glob("ml_pollution_check_*.json"))
    assert '"passed": false' in summary.read_text(encoding="utf-8")


def test_pollution_monitor_raise_on_red_blocks_evaluation_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        pollution_monitor,
        "enforce",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            constitution.ConstitutionEvaluationError("bounded test failure")
        ),
    )

    with pytest.raises(RuntimeError, match="constitution evaluation failed"):
        pollution_monitor.run_pollution_check(
            signals_root=tmp_path / "signals",
            runs_root=tmp_path / "runs",
            events_dir=tmp_path / "events",
            raise_on_red=True,
        )
