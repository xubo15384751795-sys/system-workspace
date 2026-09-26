"""Fixed Step 5A parity scenarios for the daily application boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from system_runtime.publish_admission import AUTHORITY_ALLOW, PublishAdmission
from system_runtime.publish_transaction import PublishTransaction
from system_runtime.run_outcome import (
    ADMISSION_BLOCK,
    ADMISSION_PASS,
    EXECUTION_FAILED,
    EXECUTION_SUCCESS,
    EXIT_MANDATORY_SINK_FAILURE,
    PUBLISH_COMMITTED,
    PUBLISH_NOT_PUBLISHED,
    REASON_MANDATORY_SINK_FAILED,
    REASON_REQUIRED_STEP_FAILED,
    RunOutcome,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _install_daily_coordinator_fixture(
    monkeypatch,
    tmp_path: Path,
    *,
    generation: bool,
    step_statuses: tuple[str, ...] = ("success", "success"),
    provider_monitoring: dict | None = None,
    mandatory_sink_error: bool = False,
):
    """Make the application coordinator hermetic without replacing its flow."""
    import orchestration.runner as runner
    from system_learning.operators import ingest_daily_run_to_hub as ingest_module
    from system_learning.operators import run_learning_hub_ingest as hub_module

    from verity.cli import daily_run
    from verity.runtime import _current_publish as current_publish
    from verity.runtime import _shadow_publish as shadow_publish

    output_root = tmp_path / "Output"
    bundle_root = output_root / "runs" / "step5a-fixture"
    evidence: dict[str, object] = {"steps": [], "alerts": [], "events": []}

    class FixturePlan:
        plan_digest = _digest("step5a-fixture-plan")
        compiled_plan = SimpleNamespace(plan_digest=plan_digest)

        def write(self, target: Path) -> Path:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                json.dumps({"plan_digest": self.plan_digest}, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return target

    class FixtureBundle:
        run_id = "step5a-fixture-run"
        run_dir = bundle_root

        @classmethod
        def start(cls, **_kwargs):
            cls.run_dir.mkdir(parents=True, exist_ok=True)
            return cls()

        def set_contract_digests(self, **kwargs):
            evidence.setdefault("contract_digests", {}).update(kwargs)

        def record_artifact(self, path):
            evidence.setdefault("artifacts", []).append(str(path))

        def record_step(self, **kwargs):
            evidence["steps"].append(dict(kwargs))

        def evidence_digest(self, _root):
            return _digest("step5a-fixture-evidence")

        def finalize_evidence(self):
            evidence["evidence_finalized"] = True

        def record_outcome(self, payload):
            evidence["outcome"] = dict(payload)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            (self.run_dir / "run_outcome.json").write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )

        def finish(self, *, status):
            evidence.setdefault("finish_statuses", []).append(status)
            return self.run_dir

    def fake_dagster(payload):
        evidence["payload"] = payload
        if generation:
            candidate = Path(os.environ["SYSTEM_GENERATION_DIR"])
            for relative, content in {
                "current/00_READ_ME_FIRST.md": "fixture\n",
                "current/framework_output.json": "{}\n",
                "current/status.json": "{}\n",
                "current/quality_validation.json": "{}\n",
                "judgment/latest.json": '{"decision": "WATCH"}\n',
                "trade_decision/latest.json": '{"decision": "WATCH"}\n',
                "position/paper_portfolio.json": "{}\n",
            }.items():
                path = candidate / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

        step_ids = ("harvester", "judgment")
        for index, status in enumerate(step_statuses):
            step_id = step_ids[index] if index < len(step_ids) else f"fixture_{index}"
            result = {
                "step": step_id,
                "status": status,
                "duration_s": 0.0,
                "returncode": 0 if status == "success" else 1,
            }
            payload.record_fn(result)

    fixture_plan = FixturePlan()
    monkeypatch.setattr(daily_run, "RunBundle", FixtureBundle)
    monkeypatch.setattr(daily_run, "compile_runtime_plan", lambda *_args, **_kwargs: fixture_plan)
    monkeypatch.setattr(daily_run, "_raise_open_file_limit", lambda: None)
    monkeypatch.setattr(daily_run, "_truncate_launchd_logs", lambda: None)
    monkeypatch.setattr(daily_run, "use_generation_transaction", lambda: generation)
    monkeypatch.setattr(daily_run, "use_legacy_daily_run", lambda: False)
    monkeypatch.setattr(daily_run, "check_freshness", lambda: {"verdict": "PASS"})
    monkeypatch.setattr(daily_run, "check_warnings", lambda: [])
    monkeypatch.setattr(
        daily_run,
        "run_freshness_check",
        lambda gate=None: {"verdict": "PASS", "content_freshness": []},
    )
    monkeypatch.setattr(
        daily_run,
        "should_publish",
        lambda status, _report: (status == "success", "fixture" if status == "success" else "run_not_success"),
    )
    monkeypatch.setattr(daily_run, "release_identity", lambda _root: {"release_id": "fixture-release"})
    monkeypatch.setattr(daily_run, "_refresh_live_system_index", lambda **_kwargs: None)
    monkeypatch.setattr(daily_run, "_weekly_cadence_due", lambda *_args: False)
    monkeypatch.setattr(daily_run, "_capture_traces", lambda _bundle: None)
    monkeypatch.setattr(daily_run, "_collect_feedback_pending", lambda _bundle: None)
    monkeypatch.setattr(daily_run, "publish_daily_run_observability", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        daily_run,
        "evaluate_minimum_monitoring",
        lambda *_args, **_kwargs: provider_monitoring or {"checks": {}},
    )
    monkeypatch.setattr(daily_run, "surface_dir", lambda name: output_root / name)
    monkeypatch.setattr(daily_run, "write_alert", lambda warnings, steps, **kwargs: evidence["alerts"].append(kwargs.get("outcome")))
    monkeypatch.setattr(daily_run, "write_runtime_event", lambda event, **kwargs: evidence["events"].append(event))
    monkeypatch.setattr(daily_run, "notify_daily_run_result", lambda **kwargs: evidence.setdefault("notifications", []).append(kwargs))
    monkeypatch.setattr(current_publish, "candidate_artifact_names", lambda: [])
    monkeypatch.setattr(runner, "run_daily_sequence_via_dagster", fake_dagster)
    monkeypatch.setattr(shadow_publish, "begin_shadow_candidate", lambda _run_dir: output_root / "shadow_candidate")
    monkeypatch.setattr(shadow_publish, "clear_shadow_candidate_env", lambda: None)
    monkeypatch.setattr(shadow_publish, "publish_shadow_candidate", lambda *_args, **_kwargs: {"count": 1})
    monkeypatch.setattr(daily_run, "begin_candidate", lambda _run_dir: output_root / "candidate")
    monkeypatch.setattr(daily_run, "clear_candidate_env", lambda: None)
    monkeypatch.setattr(daily_run, "publish_candidate", lambda *_args, **_kwargs: {"count": 1})
    monkeypatch.setattr(ingest_module, "ingest_daily_run_bundle", lambda *_args, **_kwargs: (_raise_sink() if mandatory_sink_error else None))
    monkeypatch.setattr(hub_module, "main", lambda: 0)
    monkeypatch.delenv("SYSTEM_SCHEDULE_LABEL", raising=False)
    monkeypatch.delenv("SYSTEM_USE_LEGACY_DAILY_RUN", raising=False)
    monkeypatch.delenv("SYSTEM_GENERATION_MODE", raising=False)
    # run_daily mutates process env for --output-root isolation; bind through
    # monkeypatch so later tests do not inherit the fixture workspace.
    for key, value in (
        ("DAILY_OUTPUT_ROOT", str(output_root)),
        ("SYSTEM_OUTPUT_ROOT", str(output_root)),
    ):
        monkeypatch.setitem(os.environ, key, value)
    for key in (
        "SYSTEM_GENERATION_DIR",
        "CURRENT_OUTPUT_DIR",
        "SYSTEM_DAILY_BUNDLE_DIR",
        "SYSTEM_DAILY_BUNDLE_RUN_ID",
        "SYSTEM_DAILY_OUTCOME_READY",
        "SYSTEM_DAILY_SINKS_COMPLETE",
        "SYSTEM_DAILY_EXIT_CODE",
        "SYSTEM_POST_PUBLISH_AUDIT_DIR",
        "ZCODE_BUNDLE_RUN_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    return daily_run, output_root, evidence


def _raise_sink():
    raise RuntimeError("fixture mandatory sink failure")


def test_dr01_dry_run_compiles_the_runtime_plan_without_publication(monkeypatch, capsys):
    from verity.cli import daily_run

    compiled: list[tuple[Path, str]] = []

    def fake_compile(paths, *, profile: str):
        compiled.append((paths.root, profile))
        return object()

    class NoBundle:
        @classmethod
        def start(cls, **_kwargs):
            raise AssertionError("dry-run must not create a run bundle")

    monkeypatch.delenv("SYSTEM_SCHEDULE_LABEL", raising=False)
    monkeypatch.setattr(daily_run, "compile_runtime_plan", fake_compile)
    monkeypatch.setattr(daily_run, "dry_run_labels", lambda: ["1. fixture"])
    monkeypatch.setattr(daily_run, "_raise_open_file_limit", lambda: None)
    monkeypatch.setattr(daily_run, "_truncate_launchd_logs", lambda: None)
    monkeypatch.setattr(daily_run, "RunBundle", NoBundle)

    outcome = daily_run.run_daily(daily_run.parse_args(["--dry-run"]))

    assert compiled and compiled[0][1] == "daily"
    assert "DRY RUN - would execute:" in capsys.readouterr().out
    assert outcome.admission_verdict == ADMISSION_PASS
    assert outcome.publish_status == PUBLISH_NOT_PUBLISHED
    assert outcome.authority_mode == "diagnostic"
    assert outcome.exit_code == 0


def test_dr02_compiled_plan_success_closes_one_daily_coordinator_outcome(monkeypatch, tmp_path: Path):
    daily_run, output_root, evidence = _install_daily_coordinator_fixture(
        monkeypatch, tmp_path, generation=False
    )

    outcome = daily_run.run_daily(
        daily_run.parse_args(["--output-root", str(output_root), "--tag", "fixture"])
    )

    assert [step["name"] for step in evidence["steps"]] == ["harvester", "judgment"]
    assert outcome.execution_status == EXECUTION_SUCCESS
    assert outcome.admission_verdict == ADMISSION_PASS
    assert outcome.publish_status == PUBLISH_COMMITTED
    assert outcome.status == "success"
    assert evidence["outcome"] == outcome.to_dict()
    assert evidence["events"][0]["outcome"] == outcome.to_dict()
    assert evidence["alerts"][0] == outcome.to_dict()
    assert outcome.exit_code == 0


def test_dr03_daily_coordinator_admission_block_preserves_live_pointer(monkeypatch, tmp_path: Path):
    daily_run, output_root, evidence = _install_daily_coordinator_fixture(
        monkeypatch,
        tmp_path,
        generation=True,
        step_statuses=("failed", "success"),
    )

    outcome = daily_run.run_daily(
        daily_run.parse_args(["--output-root", str(output_root), "--tag", "fixture"])
    )

    assert outcome.execution_status == EXECUTION_FAILED
    assert outcome.admission_verdict == ADMISSION_BLOCK
    assert outcome.publish_status == PUBLISH_NOT_PUBLISHED
    assert outcome.exit_code != 0
    assert not (output_root / "live").exists()
    assert evidence["outcome"] == outcome.to_dict()
    assert evidence["events"][0]["outcome"] == outcome.to_dict()
    assert evidence["alerts"][0] == outcome.to_dict()


def test_dr04_publication_success_materializes_generation_and_current(monkeypatch, tmp_path: Path):
    daily_run, output_root, evidence = _install_daily_coordinator_fixture(
        monkeypatch, tmp_path, generation=True
    )

    try:
        outcome = daily_run.run_daily(
            daily_run.parse_args(["--output-root", str(output_root), "--tag", "fixture"])
        )
    finally:
        os.environ.pop("SYSTEM_GENERATION_DIR", None)
        os.environ.pop("SYSTEM_CURRENT_OUTPUT_DIR", None)
        os.environ.pop("SYSTEM_SHADOW_OUTPUT_DIR", None)

    generation = output_root / "generations" / outcome.run_id
    assert outcome.admission_verdict == ADMISSION_PASS
    assert outcome.publish_status == PUBLISH_COMMITTED
    assert outcome.generation_id == outcome.run_id
    assert (output_root / "live").resolve() == generation
    assert (generation / "manifest.json").is_file()
    assert (generation / "admission.json").is_file()
    assert (generation / "lineage.json").is_file()
    manifest = json.loads((generation / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == outcome.run_id
    assert manifest["plan_digest"] == evidence["contract_digests"]["plan_digest"]
    assert evidence["outcome"] == outcome.to_dict()


def test_dr05_daily_coordinator_preserves_primary_success_on_mandatory_sink_failure(
    monkeypatch, tmp_path: Path
):
    daily_run, output_root, evidence = _install_daily_coordinator_fixture(
        monkeypatch, tmp_path, generation=False, mandatory_sink_error=True
    )

    outcome = daily_run.run_daily(
        daily_run.parse_args(["--output-root", str(output_root), "--tag", "fixture"])
    )

    assert outcome.execution_status == EXECUTION_SUCCESS
    assert outcome.admission_verdict == ADMISSION_PASS
    assert outcome.publish_status == PUBLISH_COMMITTED
    assert outcome.reason_codes == [REASON_MANDATORY_SINK_FAILED]
    assert outcome.exit_code == EXIT_MANDATORY_SINK_FAILURE
    assert evidence["outcome"] == outcome.to_dict()
    assert evidence["alerts"][-1] == outcome.to_dict()
    assert evidence["events"][-1]["outcome"] == outcome.to_dict()


def test_dr06_daily_coordinator_keeps_primary_failure_with_mandatory_sink_failure(
    monkeypatch, tmp_path: Path
):
    daily_run, output_root, evidence = _install_daily_coordinator_fixture(
        monkeypatch,
        tmp_path,
        generation=False,
        step_statuses=("failed", "success"),
        mandatory_sink_error=True,
    )

    outcome = daily_run.run_daily(
        daily_run.parse_args(["--output-root", str(output_root), "--tag", "fixture"])
    )

    assert outcome.execution_status == EXECUTION_FAILED
    assert outcome.admission_verdict == ADMISSION_BLOCK
    assert outcome.publish_status == PUBLISH_NOT_PUBLISHED
    assert outcome.failed_steps == ["harvester"]
    assert REASON_REQUIRED_STEP_FAILED in outcome.reason_codes
    assert REASON_MANDATORY_SINK_FAILED in outcome.reason_codes
    assert outcome.exit_code == EXIT_MANDATORY_SINK_FAILURE
    assert evidence["outcome"] == outcome.to_dict()
    assert evidence["alerts"][-1] == outcome.to_dict()
    assert evidence["events"][-1]["outcome"] == outcome.to_dict()


def test_dr03_admission_block_does_not_create_a_live_pointer(tmp_path: Path) -> None:
    tx = PublishTransaction("dr03-blocked", tmp_path / "Output" / "runs" / "dr03-blocked")
    tx.prepare()
    tx.activate()
    (tx.candidate_dirs["current"] / "framework_output.json").write_text("{}\n", encoding="utf-8")
    tx.write_lineage()
    token = PublishAdmission.evaluate(
        run_status="partial_failure",
        freshness_verdict="PASS",
        required_artifacts=[],
        candidate_artifacts=[],
        candidate_run_id=tx.run_id,
        authority_verdict=AUTHORITY_ALLOW,
        generation_id=tx.run_id,
        plan_digest=_digest("plan"),
        evidence_digest=_digest("evidence"),
        generation_digest=tx.generation_digest,
    )
    try:
        assert tx.admit(token) is False
        assert token.is_blocked
        assert not (tmp_path / "Output" / "live").exists()
    finally:
        tx.deactivate()


def test_dr05_mandatory_sink_failure_preserves_primary_publication_semantics() -> None:
    from verity.cli.post_run_sinks import mandatory_sink_failure_outcome

    primary = RunOutcome(
        run_id="dr05-primary-success",
        spec_status="OK",
        execution_status=EXECUTION_SUCCESS,
        admission_verdict=ADMISSION_PASS,
        publish_status=PUBLISH_COMMITTED,
        authority_mode="authoritative",
        generation_id="dr05-primary-success",
    )

    terminal = mandatory_sink_failure_outcome(primary)

    assert terminal.run_id == primary.run_id
    assert terminal.execution_status == primary.execution_status
    assert terminal.admission_verdict == primary.admission_verdict
    assert terminal.publish_status == primary.publish_status
    assert terminal.authority_mode == primary.authority_mode
    assert terminal.reason_codes == [REASON_MANDATORY_SINK_FAILED]
    assert terminal.exit_code == EXIT_MANDATORY_SINK_FAILURE
    assert terminal.status == "partial_failure"


def test_dr06_primary_failure_plus_sink_cannot_become_success() -> None:
    from verity.cli.post_run_sinks import mandatory_sink_failure_outcome

    primary = RunOutcome(
        run_id="dr06-primary-failure",
        spec_status="OK",
        execution_status=EXECUTION_FAILED,
        failed_steps=["harvester"],
        admission_verdict=ADMISSION_BLOCK,
        publish_status=PUBLISH_NOT_PUBLISHED,
        authority_mode="diagnostic",
        reason_codes=[REASON_REQUIRED_STEP_FAILED],
    )

    terminal = mandatory_sink_failure_outcome(primary)

    assert terminal.status == "partial_failure"
    assert terminal.exit_code == EXIT_MANDATORY_SINK_FAILURE
    assert terminal.admission_verdict == ADMISSION_BLOCK
    assert terminal.publish_status == PUBLISH_NOT_PUBLISHED
    assert terminal.authority_mode == "diagnostic"
    assert terminal.failed_steps == ["harvester"]
    assert terminal.reason_codes == [REASON_REQUIRED_STEP_FAILED, REASON_MANDATORY_SINK_FAILED]
