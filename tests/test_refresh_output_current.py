from __future__ import annotations

from scripts import refresh_output_current as refresh
from scripts._admission_gate import AdmissionDecision


def test_refresh_blocks_before_running_any_producer(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        refresh,
        "admit_for_consumption",
        lambda _consumer: AdmissionDecision(
            consumer="refresh_current",
            allowed=False,
            blockers=["ofr_fsi_cache:stale (behind=16d)"],
        ),
    )
    producer_calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        refresh,
        "run_step",
        lambda name, cmd: producer_calls.append((name, cmd)),
    )

    assert refresh.main([]) == 1
    assert producer_calls == []
    output = capsys.readouterr().out
    assert "Refresh blocked before any producer" in output
    assert "ofr_fsi_cache:stale" in output


def test_refresh_stops_at_first_failed_producer(monkeypatch) -> None:
    monkeypatch.setattr(
        refresh,
        "admit_for_consumption",
        lambda _consumer: AdmissionDecision(
            consumer="refresh_current",
            allowed=True,
        ),
    )
    producer_calls: list[str] = []

    def fake_run_step(name: str, _cmd: list[str]) -> dict:
        producer_calls.append(name)
        status = "failed" if name == "quality_validation" else "success"
        return {"step": name, "status": status, "duration_s": 0}

    monkeypatch.setattr(refresh, "run_step", fake_run_step)

    assert refresh.main([]) == 1
    assert producer_calls == ["neutral_pressure_measurement", "quality_validation"]


def test_dry_run_lists_admission_and_complete_daily_chain(capsys) -> None:
    assert refresh.main(["--dry-run"]) == 0
    output = capsys.readouterr().out

    assert "pre-consumption admission (hard gate)" in output
    for script in (
        "build_measurement_quality_report.py",
        "build_signal_card.py",
        "signal_consensus.py",
        "build_work_brief.py",
        "freshness_validator.py",
    ):
        assert script in output
