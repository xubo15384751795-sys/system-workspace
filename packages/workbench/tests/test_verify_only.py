from __future__ import annotations

import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[1] / "agents" / "harness"
sys.path.insert(0, str(HARNESS_ROOT))

from events import system_event_writer  # noqa: E402
from hooks.post_verify import post_verify  # noqa: E402
from workflows.verify_only import (  # noqa: E402
    CheckSelector,
    CheckSpec,
    VerificationRunner,
)


def test_verification_pass_requires_durable_event(monkeypatch) -> None:
    runner = VerificationRunner()
    monkeypatch.setattr(runner, "_write_verification_event", lambda _verdict: False)
    result = runner.run(
        [
            CheckSpec(
                "command_pass",
                "command",
                command=f"{sys.executable} -c pass",
            )
        ],
        target="source_code",
    )

    assert result.verdict == "FAIL"
    assert result.evidence["verification_event_written"] is False
    assert "verification_event_write_failed" in result.blockers


def test_verification_pass_records_event_written(monkeypatch) -> None:
    runner = VerificationRunner()
    monkeypatch.setattr(runner, "_write_verification_event", lambda _verdict: True)
    result = runner.run(
        [CheckSpec("command_pass", "command", command=f"{sys.executable} -c pass")],
        target="source_code",
    )

    assert result.verdict == "PASS"
    assert result.evidence["verification_event_written"] is True


def test_event_writer_reports_missing_or_failed_sink(monkeypatch, tmp_path: Path) -> None:
    event = system_event_writer._event("verification_result")
    monkeypatch.setattr(system_event_writer, "RECORD_SCRIPT", tmp_path / "missing.py")
    assert system_event_writer._write(event) is False

    script = tmp_path / "writer.py"
    script.write_text("raise SystemExit(3)\n", encoding="utf-8")
    monkeypatch.setattr(system_event_writer, "RECORD_SCRIPT", script)
    assert system_event_writer._write(event) is False


def test_post_verify_exposes_non_durable_event(monkeypatch) -> None:
    monkeypatch.setattr(
        system_event_writer,
        "write_verification_result",
        lambda **_kwargs: False,
    )
    result = post_verify(
        {"id": "harvester.verify_release", "subsystem": "harvester"},
        {},
        {"ok": True, "summary": "checks passed", "evidence": {"checks": []}},
        "verify",
    )

    event = result.events[0]
    assert event["event_written"] is False
    assert event["degraded"] is True
    assert result.warnings


def test_benchmark_baseline_rank_never_passes_from_print_only_placeholder(monkeypatch) -> None:
    runner = VerificationRunner()
    monkeypatch.setattr(runner, "_write_verification_event", lambda _verdict: True)
    checks = CheckSelector().select("benchmark", [], "benchmark complete")

    result = runner.run(checks, target="benchmark")

    baseline = next(check for check in result.checks if check.check_id == "baseline_rank")
    assert baseline.passed is False
    assert baseline.exit_code == 2
    assert "NOT_IMPLEMENTED" in baseline.observed
    assert result.verdict == "FAIL"


def test_markdown_link_check_validates_local_targets(tmp_path) -> None:
    document = tmp_path / "README.md"
    target = tmp_path / "guide.md"
    target.write_text("# Guide\n", encoding="utf-8")
    document.write_text(
        "[guide](guide.md#intro) [external](https://example.com/docs)\n",
        encoding="utf-8",
    )

    result = VerificationRunner()._execute(
        CheckSpec("links", "link_check", command=str(document)),
        "verify",
    )

    assert result.passed is True
    assert "validated 1 local" in result.observed


def test_markdown_link_check_rejects_missing_local_target(tmp_path) -> None:
    document = tmp_path / "README.md"
    document.write_text("[missing](missing.md)\n", encoding="utf-8")

    result = VerificationRunner()._execute(
        CheckSpec("links", "link_check", command=str(document)),
        "verify",
    )

    assert result.passed is False
    assert "missing.md" in result.observed
