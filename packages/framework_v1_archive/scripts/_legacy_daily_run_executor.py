"""Sequence-driven daily pipeline executor.

Reads step order from governance/daily_run_sequence.yaml and dispatches each
step via governance/daily_pipeline_registry.yaml metadata (command, env, mode).
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from verity.runtime._daily_run_sequence import load_daily_run_sequence, weekly_step_ids
from verity.runtime._pipeline_dag import interpret_failure
from verity.runtime._pipeline_runner import (
    load_registry,
    load_step_execution,
    run_registry_step,
)
from verity.runtime.runtime_io import ROOT, current_dir

logger = logging.getLogger(__name__)

WEEKLY_STEPS = weekly_step_ids()

# Extra CLI args not captured in registry current_command strings.
STEP_EXTRA_ARGV: dict[str, list[str]] = {
    "evaluate_pending": [],  # filled dynamically
    "record_daily_run_event": ["--skip-if-unchanged"],
}

# Per-step subprocess environments.
def _replay_env() -> dict[str, str]:
    return {
        "PYTHONPATH": os.pathsep.join([
            str(ROOT),
            str(ROOT / "scripts"),
            str(ROOT / "packages" / "workbench" / "src"),
            str(ROOT / "packages" / "framework_v1_archive" / "src"),
        ]),
    }


def _harvester_env() -> dict[str, str]:
    return {"PYTHONPATH": str(ROOT / "packages" / "harvester" / "src")}


def _workbench_env() -> dict[str, str]:
    return {"PYTHONPATH": str(ROOT / "packages" / "workbench" / "src")}


def _policy_env() -> dict[str, str]:
    return {"PYTHONPATH": f"{ROOT}:{ROOT / 'Workbench' / 'src'}:{ROOT / 'scripts'}"}


STEP_ENV: dict[str, Callable[[], dict[str, str]]] = {
    "harvester": _harvester_env,
    "regime_detection": _workbench_env,
    "build_policy_from_paper": _policy_env,
}

STEP_INPUT_ARTIFACTS: dict[str, Callable[["DailyRunContext"], list[str]]] = {
    "neutral_pressure_measurement": lambda ctx: [str(ctx.benchmark_panel_path)],
    "judgment_layer": lambda _ctx: [
        str(current_dir() / "neutral_pressure_snapshot.json"),
        str(ROOT / "Output" / "state" / "hmm_stability" / "hmm_stability_audit.json"),
    ],
    "trade_decision": lambda _ctx: [
        str(ROOT / "Output" / "judgment" / "latest.json"),
        str(ROOT / "Output" / "judgment" / "promotion_gate.json"),
        str(current_dir() / "neutral_pressure_snapshot.json"),
        str(ROOT / "Output" / "state" / "hmm_stability" / "hmm_stability_audit.json"),
    ],
}


@dataclass
class DailyRunContext:
    args: Any
    start_time: datetime
    total_steps: int
    run_step_fn: Callable[..., dict[str, Any]]
    record_fn: Callable[..., None]
    benchmark_panel_path: Path
    step_index: int = 0
    # Bundle run_id. Also published as env var ZCODE_BUNDLE_RUN_ID by the
    # caller (daily_run.py) so subprocess steps inherit it; this field is the
    # in-process mirror for the executor and callable steps.
    run_id: str = ""

    @property
    def force_weekly(self) -> bool:
        return bool(getattr(self.args, "force_weekly", False))

    @property
    def skip_harvester(self) -> bool:
        return bool(getattr(self.args, "skip_harvester", False))

    @property
    def skip_etf(self) -> bool:
        return bool(getattr(self.args, "skip_etf", False))


def _registry_step(step_id: str) -> dict[str, Any]:
    return load_registry().get("steps", {}).get(step_id, {})


def should_run_step(step_id: str, step_meta: dict[str, Any], ctx: DailyRunContext) -> tuple[bool, str]:
    skip_flag = step_meta.get("skip_flag")
    if skip_flag == "skip_harvester" and ctx.skip_harvester:
        return False, "skip_harvester"
    if skip_flag == "skip_etf" and ctx.skip_etf:
        return False, "skip_etf"

    reg = _registry_step(step_id)
    status = reg.get("status", "active")
    if status in {"archived", "inactive"}:
        return False, f"registry_{status}"

    schedule = step_meta.get("schedule") or reg.get("schedule")
    if schedule == "weekly" and not (ctx.force_weekly or ctx.start_time.weekday() == 0):
        return False, "weekly_schedule"

    return True, "run"


def _build_harvester_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "harvester",
        "--exports-root",
        str(ROOT / "Data" / "harvester" / "exports"),
        "daily-release",
    ]


def _build_regime_detection_command(ctx: DailyRunContext) -> list[str]:
    today_str = ctx.start_time.strftime("%Y-%m-%d")
    code = (
        "from pathlib import Path; from ml.regime_detector import detect_regime; "
        "import json; "
        "result = detect_regime(Path('Data/harvester/exports/latest/data/benchmark_panel.parquet'), "
        f"source_release='daily', source_created_at='{today_str}', train_window=756, write=True); "
        "print(json.dumps({'regime': result['regime']['current'], "
        "'usable': result['degeneracy']['usable_for_core_judgment'], "
        "'warnings': result['degeneracy']['warnings']}, indent=2))"
    )
    return [sys.executable, "-c", code]


def _build_collect_reviews_command() -> list[str]:
    return [sys.executable, "-m", "caselab_runtime.feedback.collect_reviews", "--json"]


def _build_evaluate_pending_argv(ctx: DailyRunContext) -> list[str]:
    if ctx.start_time.weekday() != 0 and not ctx.force_weekly:
        return ["--daily-only"]
    return []


CUSTOM_COMMAND_BUILDERS: dict[str, Callable[[DailyRunContext], list[str]]] = {
    "harvester": lambda _ctx: _build_harvester_command(),
    "regime_detection": _build_regime_detection_command,
    "collect_reviews": lambda _ctx: _build_collect_reviews_command(),
}


def _with_archive_pythonpath(
    cmd: list[str] | None,
    env: dict[str, str] | None,
) -> dict[str, str] | None:
    """Archived scripts live under scripts/archive/; keep scripts/ on PYTHONPATH."""
    if not cmd:
        return env
    joined = " ".join(cmd)
    if "scripts/archive/" not in joined:
        return env
    scripts_dir = str(ROOT / "scripts")
    merged = dict(env or {})
    existing = merged.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    if scripts_dir not in parts:
        parts.insert(0, scripts_dir)
    merged["PYTHONPATH"] = os.pathsep.join(parts)
    return merged


def build_step_invocation(step_id: str, ctx: DailyRunContext) -> tuple[str, list[str] | None, dict[str, str] | None]:
    """Return (mode, command_or_argv, env) for run_step_fn / run_registry_step."""
    execution = load_step_execution(step_id)
    mode = execution.get("mode", "subprocess")
    env_factory = STEP_ENV.get(step_id)
    env = env_factory() if env_factory else None

    extra_argv = list(STEP_EXTRA_ARGV.get(step_id, []))
    if step_id == "evaluate_pending":
        extra_argv = _build_evaluate_pending_argv(ctx)

    if step_id in CUSTOM_COMMAND_BUILDERS:
        cmd = CUSTOM_COMMAND_BUILDERS[step_id](ctx) + extra_argv
        return "subprocess", cmd, _with_archive_pythonpath(cmd, env)

    if mode == "callable":
        return "callable", extra_argv or None, env

    current = execution.get("current_command", "")
    if not current:
        reg = _registry_step(step_id)
        current = reg.get("command", "")
    if not current:
        raise ValueError(f"{step_id} has no execution command")

    cmd = current.split()
    if cmd and cmd[0] == "python":
        cmd[0] = sys.executable
    elif cmd and not Path(cmd[0]).is_absolute() and cmd[0].endswith(".py"):
        cmd = [sys.executable, str(ROOT / cmd[0])] + cmd[1:]
    cmd.extend(extra_argv)
    return "subprocess", cmd, _with_archive_pythonpath(cmd, env)


def execute_step(step_id: str, ctx: DailyRunContext) -> dict[str, Any]:
    mode, cmd_or_argv, env = build_step_invocation(step_id, ctx)
    if mode == "callable":
        return run_registry_step(step_id, mode="callable", argv=cmd_or_argv, env=env)
    assert cmd_or_argv is not None
    return ctx.run_step_fn(step_id, cmd_or_argv, env=env, registry_step=step_id)


def execute_daily_sequence(ctx: DailyRunContext) -> list[dict[str, Any]]:
    """Run all sequence steps that pass schedule/skip/registry gates."""
    sequence = load_daily_run_sequence()
    results: list[dict[str, Any]] = []

    for index, step_meta in enumerate(sequence, start=1):
        step_id = str(step_meta.get("id", ""))
        if not step_id:
            continue
        ctx.step_index = index

        run, reason = should_run_step(step_id, step_meta, ctx)
        if not run:
            logger.info("[%d/%d] Skipping %s (%s)", index, ctx.total_steps, step_id, reason)
            continue

        # Failure-behavior interpreter: decide whether to block, degrade, or run
        # this step based on which upstream steps already failed and their
        # declared failure_behavior. This is the runtime enforcement of the
        # registry's block_*/hold_flat/lower_claim_ceiling/continue_with_warning
        # semantics. Replaces the Phase A boolean failed_upstream_of with
        # per-behavior discrimination so hold_flat/lower_claim_ceiling upstreams
        # degrade-and-continue instead of hard-blocking.
        decision = interpret_failure(step_id, results)
        if decision["action"] == "block":
            blocked_by = decision["blocked_by"]
            logger.warning(
                "[%d/%d] Blocking %s (upstream failed: %s)",
                index,
                ctx.total_steps,
                step_id,
                ", ".join(blocked_by),
            )
            result = {
                "step": step_id,
                "status": "blocked_upstream",
                "blocked_by": blocked_by,
                "duration_s": 0,
            }
            input_builder = STEP_INPUT_ARTIFACTS.get(step_id)
            input_artifacts = input_builder(ctx) if input_builder else None
            ctx.record_fn(result, input_artifacts=input_artifacts)
            results.append(result)
            continue

        degraded = decision.get("degraded", False)
        if degraded:
            logger.info(
                "[%d/%d] Running %s in degraded mode (upstream: %s)",
                index, ctx.total_steps, step_id,
                ", ".join(decision.get("degraded_by", [])),
            )

        logger.info("[%d/%d] Running %s...", index, ctx.total_steps, step_id)
        try:
            result = execute_step(step_id, ctx)
        except ValueError as exc:
            result = {
                "step": step_id,
                "status": "error",
                "error": str(exc),
                "duration_s": 0,
            }

        # Tag the result degraded if the interpreter said so (hold_flat or
        # lower_claim_ceiling upstream). The step still ran and produced output.
        if degraded and result.get("status") == "success":
            result["degraded"] = True
            result["degraded_by"] = decision.get("degraded_by", [])

        input_builder = STEP_INPUT_ARTIFACTS.get(step_id)
        input_artifacts = input_builder(ctx) if input_builder else None
        ctx.record_fn(result, input_artifacts=input_artifacts)
        results.append(result)

    return results
