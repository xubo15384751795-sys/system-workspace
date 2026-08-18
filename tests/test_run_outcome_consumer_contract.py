"""Hermetic contract for the shared RunOutcome consumer boundary."""
from __future__ import annotations

import json
from pathlib import Path

from scripts import _notify, daily_run
from scripts.run_bundle import RunBundle
from system_runtime.run_outcome import RunOutcome


def _event_payloads(runtime_events: Path) -> list[dict]:
    paths = sorted(runtime_events.glob("*.jsonl"))
    assert len(paths) == 1
    return [
        json.loads(line)["payload"]
        for line in paths[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_failed_runoutcome_is_identical_in_bundle_event_alert_and_notification(
    monkeypatch, tmp_path: Path
) -> None:
    outcome = RunOutcome(
        run_id="fixture-failed-run",
        spec_status="OK",
        execution_status="FAILED",
        failed_steps=["harvester"],
        blocked_steps=["judgment_layer"],
        admission_verdict="BLOCK",
        publish_status="NOT_PUBLISHED",
        authority_mode="authoritative",
        reason_codes=["REQUIRED_STEP_FAILED", "STEP_BLOCKED"],
        generation_id="fixture-failed-run",
        release_id="fixture-release",
    )
    payload = outcome.to_dict()

    bundle = RunBundle.start(root=tmp_path, mode="fixture", update_pointer=False)
    bundle.record_outcome(payload)
    run_dir = bundle.finish(status=outcome.status)

    output_root = tmp_path / "Output"
    daily_run.write_alert(
        ["fixture warning"],
        [{"step": "harvester", "status": "failed"}],
        output_root=output_root,
        outcome=payload,
    )
    daily_run.write_runtime_event(
        {"type": "fixture_daily_run", "run_id": outcome.run_id, "outcome": payload},
        output_root=output_root,
    )

    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(
        _notify,
        "notify_deviations",
        lambda title, deviations, **_kwargs: notifications.append(
            (title, "; ".join(deviations))
        )
        or True,
    )
    _notify.notify_daily_run_result(
        status=outcome.status,
        failed_steps=outcome.failed_steps,
        warnings=["fixture warning"],
        outcome=payload,
    )

    bundle_payload = json.loads((run_dir / "run_outcome.json").read_text(encoding="utf-8"))
    alert_payload = json.loads((output_root / "alerts" / "latest_alert.json").read_text(encoding="utf-8"))
    event_payload = _event_payloads(output_root / "runtime_events")[0]

    assert bundle_payload == payload
    assert alert_payload["outcome"] == payload
    assert event_payload["outcome"] == payload
    assert notifications == [
        (
            "System daily_run failed",
            "failed step: harvester; outcome; exit_code=3; admission=BLOCK; publish=NOT_PUBLISHED",
        )
    ]
