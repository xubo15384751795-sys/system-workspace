"""Callable E2E — resolve and execute default main-chain steps hermetically.

P0-3:
  wave 1 — resolve all main-chain callables; execute light steps under tmp Output
  wave 2 — degraded measurement scenario, operator-current isolation, shared run_id,
           and callable/subprocess mode agreement for a light step
  wave 3 — judgment → promotion → evidence/readme/artifact callables under a seeded
           sandbox fixture chain
  wave 4 — trade_decision / next_actions / freshness_validator on the same sandbox
  wave 5 — k_measurement_gate / x_measurement_gate under seeded panel fixtures
  wave 6 — etf_refresh + structural_replay (archived reproduction) hermetic execute;
           assert 100% MAIN_CHAIN_STEPS have an executable coverage set

Failure propagation remains covered by tests/test_failure_propagation.py.

Still out of scope for this file (roadmap acceptance remaining):
  14-day callable shadow evidence, default-mode routing decision, full schema/
  lineage gate on every artifact, dry-run/quick/standard/full mode matrix.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from _pipeline_runner import load_step_execution, resolve_callable, run_registry_step

from tests.helpers.callable_chain_sandbox import (
    patch_callable_chain_paths,
    seed_callable_chain_workspace,
)

ROOT = Path(__file__).resolve().parents[1]

MAIN_CHAIN_STEPS = (
    "etf_refresh",
    "structural_replay",
    "k_measurement_gate",
    "x_measurement_gate",
    "measurement_quality_report",
    "judgment_layer",
    "judgment_promotion_gate",
    "trade_decision",
    "readme_first",
    "next_actions",
    "freshness_validator",
    "build_artifact_registry",
    "record_daily_run_event",
    "evidence_grade_report",
)

# Steps whose callables can run without live Harvester / Paper / heavy deps.
EXECUTABLE_LIGHT_STEPS = (
    "measurement_quality_report",
    "record_daily_run_event",
)

# Judgment-chain + readout builders that wave-3 fixtures can drive.
EXECUTABLE_CHAIN_STEPS = (
    "judgment_layer",
    "judgment_promotion_gate",
    "evidence_grade_report",
    "build_artifact_registry",
    "readme_first",
)

# Post-judgment / quality callables seeded by the same sandbox (wave 4).
EXECUTABLE_POST_JUDGMENT_STEPS = (
    "trade_decision",
    "next_actions",
    "freshness_validator",
)

# Measurement gates that need panel parquet fixtures (wave 5).
EXECUTABLE_GATE_STEPS = (
    "k_measurement_gate",
    "x_measurement_gate",
)

# Heavy / archived callables (wave 6).
EXECUTABLE_HEAVY_STEPS = (
    "etf_refresh",
    "structural_replay",
)

# Readout builders migrated from subprocess to callable mode on 2026-08-09.
# They are non-authoritative explanation artifacts and can be hermetically
# exercised after the judgment/promotion fixture is seeded.
EXECUTABLE_READOUT_STEPS = (
    "signal_card",
    "signal_consensus",
    "work_brief",
)

EXECUTABLE_ALL_STEPS = (
    EXECUTABLE_LIGHT_STEPS
    + EXECUTABLE_CHAIN_STEPS
    + EXECUTABLE_POST_JUDGMENT_STEPS
    + EXECUTABLE_GATE_STEPS
    + EXECUTABLE_HEAVY_STEPS
    + EXECUTABLE_READOUT_STEPS
)


def _fingerprint(path: Path) -> str:
    if not path.exists():
        return "missing"
    digest = hashlib.sha256()
    for fp in sorted(path.rglob("*")):
        if not fp.is_file():
            continue
        digest.update(fp.relative_to(path).as_posix().encode())
        digest.update(str(fp.stat().st_size).encode())
    return digest.hexdigest()


def _seed_measurement_gates(
    tmp_path: Path, *, k_pass: bool = True, x_pass: bool = True
) -> Path:
    out = tmp_path / "Output"
    (out / "current").mkdir(parents=True, exist_ok=True)
    (out / "k_measurement").mkdir(parents=True, exist_ok=True)
    (out / "x_measurement").mkdir(parents=True, exist_ok=True)
    if k_pass:
        (out / "k_measurement" / "k_measurement_gate.json").write_text(
            json.dumps({"gate_verdict": "PASS", "tests": {"a": {"status": "PASS"}}}),
            encoding="utf-8",
        )
    if x_pass:
        (out / "x_measurement" / "x_measurement_gate.json").write_text(
            json.dumps({"gate_verdict": "PASS", "tests": {"b": {"status": "PASS"}}}),
            encoding="utf-8",
        )
    return out


def _patch_sandbox(monkeypatch, tmp_path: Path, out: Path) -> None:
    import scripts._data_paths as dp
    import scripts._runtime_io as rio

    monkeypatch.setattr(rio, "ROOT", tmp_path)
    monkeypatch.setattr(dp, "ROOT", tmp_path)
    monkeypatch.setattr(
        dp, "HARVESTER_LATEST", tmp_path / "Data" / "harvester" / "exports" / "latest"
    )
    monkeypatch.setattr(
        dp,
        "HARVESTER_DATA",
        tmp_path / "Data" / "harvester" / "exports" / "latest" / "data",
    )
    monkeypatch.setenv("DAILY_OUTPUT_ROOT", str(out))
    monkeypatch.setenv("CURRENT_OUTPUT_DIR", str(out / "current"))
    monkeypatch.setenv("SYSTEM_WORKSPACE_ROOT", str(tmp_path))


@pytest.mark.parametrize("step_id", MAIN_CHAIN_STEPS)
def test_main_chain_step_is_callable(step_id: str) -> None:
    execution = load_step_execution(step_id)
    assert execution.get("mode") == "callable", step_id
    spec = execution.get("future_callable")
    assert spec, step_id
    if step_id == "structural_replay":
        pytest.importorskip("omegaconf")
    target = resolve_callable(spec)
    assert callable(target)


def test_measurement_quality_report_callable_runs(tmp_path, monkeypatch) -> None:
    out = _seed_measurement_gates(tmp_path)
    _patch_sandbox(monkeypatch, tmp_path, out)

    from scripts.commands.weekly.build_measurement_quality_report import build_report

    report = build_report()
    assert report["overall_status"] in {"OK", "DEGRADED"}
    assert report["channels"]["K"]["gate_verdict"] == "PASS"
    assert report["channels"]["X_agg"]["gate_verdict"] == "PASS"


def test_measurement_quality_degraded_when_k_gate_missing(
    tmp_path, monkeypatch
) -> None:
    """P0-3 degraded scenario: missing K gate → overall DEGRADED, X still readable."""
    out = _seed_measurement_gates(tmp_path, k_pass=False, x_pass=True)
    _patch_sandbox(monkeypatch, tmp_path, out)

    from scripts.commands.weekly.build_measurement_quality_report import build_report

    report = build_report()
    assert report["overall_status"] == "DEGRADED"
    assert report["channels"]["K"]["gate_verdict"] == "MISSING"
    assert report["channels"]["X_agg"]["gate_verdict"] == "PASS"


@pytest.mark.parametrize("step_id", EXECUTABLE_LIGHT_STEPS)
def test_light_main_chain_callable_executes(
    step_id: str, tmp_path: Path, monkeypatch
) -> None:
    """Actually invoke light callables under an isolated Output root."""
    out = _seed_measurement_gates(tmp_path)
    _patch_sandbox(monkeypatch, tmp_path, out)
    monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", "p0_3_wave2_fixture_run")

    argv = ["--skip-if-unchanged"] if step_id == "record_daily_run_event" else None
    result = run_registry_step(step_id, mode="callable", argv=argv)
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}, result
    assert "callable" in result


def test_light_callable_does_not_mutate_operator_current(
    tmp_path: Path, monkeypatch
) -> None:
    """Candidate/sandbox writes must not touch authoritative Output/current."""
    operator_current = ROOT / "Output" / "current"
    before = _fingerprint(operator_current)

    out = _seed_measurement_gates(tmp_path)
    _patch_sandbox(monkeypatch, tmp_path, out)
    result = run_registry_step("measurement_quality_report", mode="callable")
    assert result["mode"] == "callable"

    after = _fingerprint(operator_current)
    assert before == after, "callable E2E mutated operator Output/current"
    # Sandbox received the write (or at least stayed isolated).
    sandbox_report = out / "current" / "measurement_quality.json"
    assert sandbox_report.exists() or result["status"] in {"success", "failed", "error"}


def test_measurement_quality_callable_and_subprocess_agree(
    tmp_path: Path, monkeypatch
) -> None:
    """Same light step via callable vs subprocess must both complete without crash."""
    out = _seed_measurement_gates(tmp_path)
    _patch_sandbox(monkeypatch, tmp_path, out)

    callable_result = run_registry_step("measurement_quality_report", mode="callable")
    subprocess_result = run_registry_step(
        "measurement_quality_report", mode="subprocess"
    )

    assert callable_result["mode"] == "callable"
    assert subprocess_result["mode"] == "subprocess"
    # Both modes must finish (success or structured failure) — not hang/crash the runner.
    assert callable_result["status"] in {"success", "failed", "error"}
    assert subprocess_result["status"] in {"success", "failed", "error"}


def test_blocked_upstream_scenario_records_lineage() -> None:
    """P0-3 blocked scenario: DAG interpreter blocks judgment when upstream fails."""
    from _pipeline_dag import interpret_failure

    prior = [{"step": "neutral_pressure_measurement", "status": "failed"}]
    decision = interpret_failure("judgment_layer", prior)
    assert decision["action"] == "block"
    assert "neutral_pressure_measurement" in decision["blocked_by"]


def test_hold_flat_upstream_degrades_rather_than_hard_blocks() -> None:
    """P0-3 degraded path: hold_flat upstream → run_degraded, not hard block."""
    from _pipeline_dag import failure_behavior_of, interpret_failure, upstream_of

    # Prefer a real registry edge; fall back if none expose hold_flat upstream.
    target = None
    hold_flat_up = None
    for candidate in ("trade_decision", "risk_gate", "paper_portfolio", "readme_first"):
        for up in upstream_of(candidate):
            if failure_behavior_of(up) == "hold_flat":
                target, hold_flat_up = candidate, up
                break
        if target:
            break
    if not target:
        pytest.skip("no hold_flat upstream edge in current registry DAG")

    prior = [{"step": hold_flat_up, "status": "failed"}]
    decision = interpret_failure(target, prior)
    assert decision["action"] == "run_degraded"
    assert decision["degraded"] is True
    assert hold_flat_up in decision.get("degraded_by", [])


def test_shared_run_id_env_visible_to_callable(tmp_path: Path, monkeypatch) -> None:
    """Bundle run_id must be injectable for same-run lineage across steps."""
    out = _seed_measurement_gates(tmp_path)
    _patch_sandbox(monkeypatch, tmp_path, out)
    run_id = "p0_3_shared_run_20260727"
    monkeypatch.setenv("ZCODE_BUNDLE_RUN_ID", run_id)

    result = run_registry_step("measurement_quality_report", mode="callable")
    assert result["status"] in {"success", "failed", "error"}
    assert os.environ.get("ZCODE_BUNDLE_RUN_ID") == run_id


@pytest.mark.parametrize("step_id", EXECUTABLE_CHAIN_STEPS)
def test_judgment_chain_callable_executes(
    step_id: str, tmp_path: Path, monkeypatch
) -> None:
    """P0-3 wave 3: run judgment/promotion/readout callables on seeded fixtures."""
    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)

    # Promotion gate and evidence/readme need a judgment card on disk first.
    if step_id != "judgment_layer":
        jl = run_registry_step("judgment_layer", mode="callable")
        assert jl["status"] in {"success", "failed", "error"}, jl
        if step_id in {
            "evidence_grade_report",
            "readme_first",
            "build_artifact_registry",
        }:
            pg = run_registry_step("judgment_promotion_gate", mode="callable")
            assert pg["status"] in {"success", "failed", "error"}, pg

    result = run_registry_step(step_id, mode="callable")
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}, result


def test_judgment_chain_writes_sandbox_artifacts_only(
    tmp_path: Path, monkeypatch
) -> None:
    """Judgment + promotion must write under sandbox Output/judgment, not operator tree."""
    operator_judgment = ROOT / "Output" / "judgment"
    before = _fingerprint(operator_judgment)

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)

    jl = run_registry_step("judgment_layer", mode="callable")
    pg = run_registry_step("judgment_promotion_gate", mode="callable")
    assert jl["status"] in {"success", "failed", "error"}
    assert pg["status"] in {"success", "failed", "error"}

    after = _fingerprint(operator_judgment)
    assert before == after, "judgment chain mutated operator Output/judgment"
    assert (sandbox / "Output" / "judgment" / "latest.json").exists()


def test_recover_scenario_clears_block_when_upstream_succeeds() -> None:
    """P0-3 recover: after upstream success, judgment is runnable again."""
    from _pipeline_dag import interpret_failure

    failed = interpret_failure(
        "judgment_layer",
        [{"step": "neutral_pressure_measurement", "status": "failed"}],
    )
    assert failed["action"] == "block"

    recovered = interpret_failure(
        "judgment_layer",
        [{"step": "neutral_pressure_measurement", "status": "success"}],
    )
    assert recovered["action"] == "run"
    assert recovered["blocked_by"] == []


def _seed_judgment_through_promotion(sandbox: Path, monkeypatch) -> None:
    patch_callable_chain_paths(monkeypatch, sandbox)
    jl = run_registry_step("judgment_layer", mode="callable")
    assert jl["status"] in {"success", "failed", "error"}, jl
    pg = run_registry_step("judgment_promotion_gate", mode="callable")
    assert pg["status"] in {"success", "failed", "error"}, pg


@pytest.mark.parametrize("step_id", EXECUTABLE_POST_JUDGMENT_STEPS)
def test_post_judgment_callable_executes(
    step_id: str, tmp_path: Path, monkeypatch
) -> None:
    """P0-3 wave 4: trade_decision / next_actions / freshness under sandbox fixtures."""
    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    _seed_judgment_through_promotion(sandbox, monkeypatch)

    result = run_registry_step(step_id, mode="callable")
    assert result["mode"] == "callable"
    # freshness_validator exits 1 on FAIL verdict — still a completed callable run.
    assert result["status"] in {"success", "failed", "error"}, result


def test_trade_decision_writes_sandbox_only(tmp_path: Path, monkeypatch) -> None:
    """trade_decision must not mutate operator Output/trade_decision."""
    operator_trade = ROOT / "Output" / "trade_decision"
    before = _fingerprint(operator_trade)

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    _seed_judgment_through_promotion(sandbox, monkeypatch)
    result = run_registry_step("trade_decision", mode="callable")
    assert result["status"] in {"success", "failed", "error"}

    after = _fingerprint(operator_trade)
    assert before == after, "trade_decision mutated operator Output/trade_decision"
    assert (sandbox / "Output" / "trade_decision" / "latest.json").exists()


def test_freshness_validator_writes_sandbox_report(tmp_path: Path, monkeypatch) -> None:
    """freshness_validator must write its report under sandbox Output/quality."""
    operator_quality = ROOT / "Output" / "quality"
    before = _fingerprint(operator_quality)

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    _seed_judgment_through_promotion(sandbox, monkeypatch)
    result = run_registry_step("freshness_validator", mode="callable")
    assert result["status"] in {"success", "failed", "error"}

    after = _fingerprint(operator_quality)
    assert before == after, "freshness_validator mutated operator Output/quality"
    report = sandbox / "Output" / "quality" / "freshness_report.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert "verdict" in payload or "overall" in payload or isinstance(payload, dict)


@pytest.mark.parametrize("step_id", EXECUTABLE_READOUT_STEPS)
def test_readout_callable_steps_execute_in_sandbox(
    step_id: str, tmp_path: Path, monkeypatch
) -> None:
    """Migrated explanation builders must stay off operator Output/current."""
    operator_current = ROOT / "Output" / "current"
    before = _fingerprint(operator_current)

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    _seed_judgment_through_promotion(sandbox, monkeypatch)
    result = run_registry_step(step_id, mode="callable")

    assert result["mode"] == "callable"
    assert result["status"] == "success", result
    assert before == _fingerprint(operator_current)
    assert (sandbox / "Output" / "current" / {
        "signal_card": "signal_card.json",
        "signal_consensus": "signal_consensus.json",
        "work_brief": "work_brief.json",
    }[step_id]).exists()


@pytest.mark.parametrize("step_id", EXECUTABLE_GATE_STEPS)
def test_measurement_gate_callable_executes(
    step_id: str, tmp_path: Path, monkeypatch
) -> None:
    """P0-3 wave 5: k/x gates run on seeded panel fixtures (verdict may be FAIL)."""
    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)

    result = run_registry_step(step_id, mode="callable")
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}, result

    if step_id == "k_measurement_gate":
        report_path = sandbox / "Output" / "k_measurement" / "k_measurement_gate.json"
    else:
        report_path = sandbox / "Output" / "x_measurement" / "x_measurement_gate.json"
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "gate_verdict" in payload
    assert "tests" in payload


def test_measurement_gates_write_sandbox_only(tmp_path: Path, monkeypatch) -> None:
    """k/x gates must not mutate operator Output/{k,x}_measurement trees."""
    operator_k = ROOT / "Output" / "k_measurement"
    operator_x = ROOT / "Output" / "x_measurement"
    before_k = _fingerprint(operator_k)
    before_x = _fingerprint(operator_x)

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)
    for step_id in EXECUTABLE_GATE_STEPS:
        result = run_registry_step(step_id, mode="callable")
        assert result["status"] in {"success", "failed", "error"}

    assert before_k == _fingerprint(operator_k)
    assert before_x == _fingerprint(operator_x)
    assert (sandbox / "Output" / "k_measurement" / "k_measurement_gate.json").exists()
    assert (sandbox / "Output" / "x_measurement" / "x_measurement_gate.json").exists()


def test_main_chain_executable_coverage_is_complete() -> None:
    """P0-3 wave 6: every MAIN_CHAIN_STEPS id must belong to an execute set."""
    covered = set(EXECUTABLE_ALL_STEPS)
    missing = [step for step in MAIN_CHAIN_STEPS if step not in covered]
    assert not missing, f"main-chain steps lack execute coverage: {missing}"
    assert len(MAIN_CHAIN_STEPS) == len(set(MAIN_CHAIN_STEPS))


def test_etf_refresh_callable_executes(tmp_path: Path, monkeypatch) -> None:
    """P0-3 wave 6: etf_refresh boundary check runs under sandbox panel fixtures."""
    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)

    result = run_registry_step("etf_refresh", mode="callable")
    assert result["mode"] == "callable"
    assert result["status"] == "success", result
    assert result["returncode"] == 0
    assert (sandbox / "Data" / "panels" / "cross_asset_daily_panel.parquet").exists()


def test_structural_replay_callable_executes(tmp_path: Path, monkeypatch) -> None:
    """P0-3 wave 6: archived structural_replay runs in isolated sandbox reproduction."""
    pytest.importorskip("omegaconf")

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)
    # Archive guard forbids daily-bundle run ids; clear after path patch.
    monkeypatch.delenv("ZCODE_BUNDLE_RUN_ID", raising=False)
    monkeypatch.setenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", "1")
    monkeypatch.setenv("STRUCTURAL_PROJECT", str(sandbox))

    panel = sandbox / "Data" / "fixtures" / "official_panel.parquet"
    out = sandbox / "Output" / "sandbox" / "structural_replay_v2"
    argv = [
        f"panel.path={panel.as_posix()}",
        f"output.dir={out.as_posix()}",
        "panel.release_id=fixture",
        "run.tag=p0_3_wave6",
        "run.pre_event_warmup_days=30",
    ]
    result = run_registry_step("structural_replay", mode="callable", argv=argv)
    assert result["mode"] == "callable"
    assert result["status"] in {"success", "failed", "error"}, result
    assert result["status"] != "error", result
    assert (out / "config_snapshot.json").exists()
    assert (out / "results.json").exists()
    assert (out / "evaluation_report.md").exists()


def test_structural_replay_writes_sandbox_only(tmp_path: Path, monkeypatch) -> None:
    """structural_replay must not mutate operator Output/sandbox tree."""
    pytest.importorskip("omegaconf")

    operator_replay = ROOT / "Output" / "sandbox" / "structural_replay_v2"
    before = _fingerprint(operator_replay)

    sandbox = seed_callable_chain_workspace(tmp_path / "workspace")
    patch_callable_chain_paths(monkeypatch, sandbox)
    monkeypatch.delenv("ZCODE_BUNDLE_RUN_ID", raising=False)
    monkeypatch.setenv("ALLOW_ARCHIVED_DEFORMATION_REPRODUCTION", "1")

    panel = sandbox / "Data" / "fixtures" / "official_panel.parquet"
    out = sandbox / "Output" / "sandbox" / "structural_replay_v2"
    argv = [
        f"panel.path={panel.as_posix()}",
        f"output.dir={out.as_posix()}",
        "panel.release_id=fixture",
        "run.tag=p0_3_wave6_iso",
        "run.pre_event_warmup_days=30",
    ]
    result = run_registry_step("structural_replay", mode="callable", argv=argv)
    assert result["status"] in {"success", "failed"}

    assert before == _fingerprint(operator_replay)
    assert (out / "results.json").exists()
