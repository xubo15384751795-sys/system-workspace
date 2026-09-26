"""Hermetic contract for the emergency legacy daily-run branch.

The legacy executor is allowed to replace only the step-dispatch mechanism.
Publication, RunOutcome construction, and all result consumers remain in the
same ``verity.cli.daily_run.run_daily`` function as the default Dagster path.
"""
from __future__ import annotations

import json
from types import SimpleNamespace


def test_legacy_dispatch_reaches_the_common_typed_outcome_sinks(monkeypatch, tmp_path):
    from system_learning.operators import (
        ingest_daily_run_to_hub,
        run_learning_hub_ingest,
    )

    from verity.cli import daily_run
    from verity.runtime import _current_publish as current_publish
    from verity.runtime import _legacy_daily_run_executor as legacy
    from verity.runtime import _shadow_publish as shadow_publish
    top_level_ingest = ingest_daily_run_to_hub

    output_root = tmp_path / "Output"
    bundle_root = output_root / "runs" / "legacy-fixture-run"
    bundle_root.mkdir(parents=True)
    executed: list[str] = []
    sinks: dict[str, object] = {}

    class FakeBundle:
        run_id = "legacy-fixture-run"
        run_dir = bundle_root

        @classmethod
        def start(cls, **_kwargs):
            return cls()

        def set_contract_digests(self, **_kwargs):
            return None

        def record_step(self, **_kwargs):
            return None

        def record_artifact(self, _path):
            return None

        def add_feedback_pending(self, *_args, **_kwargs):
            return None

        def capture_decision_trace(self, _payload):
            return None

        def capture_signal_trace(self, _payload):
            return None

        def record_outcome(self, payload):
            sinks["bundle"] = payload
            (self.run_dir / "run_outcome.json").write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )

        def finish(self, *, status):
            sinks["finish_status"] = status
            return self.run_dir

    def fake_execute_step(step_id, _ctx):
        executed.append(step_id)
        return {"step": step_id, "status": "success", "duration_s": 0.0, "returncode": 0}

    def fake_alert(_warnings, _steps, *, output_root=None, outcome=None, **_kwargs):
        sinks["alert"] = outcome

    def fake_event(event, *, output_root=None):
        sinks["event"] = event

    def fake_notify(
        *,
        status,
        failed_steps,
        warnings,
        outcome,
        canonical_lineage=None,
        content_stale=None,
        publish_blocked=None,
    ):
        sinks["notification"] = outcome
        sinks["notification_status"] = status
        sinks["notification_lineage"] = canonical_lineage
        sinks["notification_content_stale"] = content_stale
        sinks["notification_publish_blocked"] = publish_blocked

    monkeypatch.setenv("SYSTEM_USE_LEGACY_DAILY_RUN", "1")
    monkeypatch.delenv("SYSTEM_GENERATION_MODE", raising=False)
    monkeypatch.delenv("SYSTEM_SCHEDULE_LABEL", raising=False)
    monkeypatch.setattr(daily_run, "RunBundle", FakeBundle)
    monkeypatch.setattr(
        daily_run,
        "load_pipeline",
        lambda _paths: SimpleNamespace(plan_digest="fixture-plan-digest"),
    )
    monkeypatch.setattr(daily_run, "_truncate_launchd_logs", lambda: None)
    monkeypatch.setattr(daily_run, "run_step", lambda *args, **kwargs: fake_execute_step(args[0], None))
    monkeypatch.setattr(legacy, "execute_step", fake_execute_step)
    monkeypatch.setattr(daily_run, "_capture_traces", lambda _bundle: None)
    monkeypatch.setattr(daily_run, "_collect_feedback_pending", lambda _bundle: None)
    monkeypatch.setattr(daily_run, "check_freshness", lambda: {"verdict": "PASS"})
    # run_freshness_check feeds the hard-notification fields (content_stale);
    # stub it too so the contract test stays hermetic against real workspace
    # freshness state.
    monkeypatch.setattr(
        daily_run, "run_freshness_check", lambda gate=None: {"verdict": "PASS"}
    )
    monkeypatch.setattr(daily_run, "check_warnings", lambda: [])
    monkeypatch.setattr(daily_run, "should_publish", lambda *_args: (True, "fixture"))
    monkeypatch.setattr(daily_run, "begin_candidate", lambda _run_dir: tmp_path / "candidate")
    monkeypatch.setattr(daily_run, "publish_candidate", lambda *_args, **_kwargs: {"count": 0})
    monkeypatch.setattr(daily_run, "clear_candidate_env", lambda: None)
    monkeypatch.setattr(shadow_publish, "begin_shadow_candidate", lambda _run_dir: tmp_path / "shadow")
    monkeypatch.setattr(shadow_publish, "publish_shadow_candidate", lambda *_args, **_kwargs: {"count": 0})
    monkeypatch.setattr(shadow_publish, "clear_shadow_candidate_env", lambda: None)
    monkeypatch.setattr(daily_run, "evaluate_minimum_monitoring", lambda *_args, **_kwargs: {
        "status": "PASS",
        "checks": {"provider_failure": {"status": "PASS"}},
    })
    monkeypatch.setattr(daily_run, "release_identity", lambda _root: {"release_id": "fixture-release"})
    monkeypatch.setattr(daily_run, "write_alert", fake_alert)
    monkeypatch.setattr(daily_run, "write_runtime_event", fake_event)
    monkeypatch.setattr(daily_run, "notify_daily_run_result", fake_notify)
    monkeypatch.setattr(daily_run, "subprocess", SimpleNamespace(run=lambda *args, **kwargs: None))
    monkeypatch.setattr(
        daily_run,
        "surface_dir",
        lambda _surface: output_root / "current",
    )
    monkeypatch.setattr(current_publish, "candidate_artifact_names", lambda: [])
    monkeypatch.setattr(ingest_daily_run_to_hub, "ingest_daily_run_bundle", lambda *args, **kwargs: None)
    monkeypatch.setattr(top_level_ingest, "ingest_daily_run_bundle", lambda *args, **kwargs: None)
    monkeypatch.setattr(run_learning_hub_ingest, "main", lambda: 0)

    outcome = daily_run.run_daily(
        daily_run.parse_args(["--output-root", str(output_root), "--tag", "fixture"])
    )

    assert executed, "legacy executor did not dispatch any sequence step"
    assert outcome.status == "success"
    assert outcome.exit_code == 0
    outcome_payload = outcome.to_dict()
    assert sinks["bundle"] == outcome_payload
    assert sinks["event"]["outcome"] == outcome_payload
    assert sinks["alert"] == outcome_payload
    assert sinks["notification"] == outcome_payload
    assert sinks["notification_status"] == outcome.status
    assert json.loads((bundle_root / "run_outcome.json").read_text(encoding="utf-8")) == outcome_payload
