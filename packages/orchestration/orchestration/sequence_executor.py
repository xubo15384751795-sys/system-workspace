"""Registry-driven daily pipeline sequence executor (canonical location).

Authority for step order and failure behavior remains
``governance/daily_pipeline_registry.yaml`` / the compiled sequence view.
Dagster jobs call into this module; they do not duplicate the step list.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, cast

from orchestration.canonical_lineage import attach_output_lineage
from orchestration.daily_run_sequence import weekly_step_ids
from orchestration.pipeline_runner import _command_args, run_callable_step
from system_runtime.context import RuntimeContext
from system_runtime.pipeline import CompiledPlan, load_pipeline

logger = logging.getLogger(__name__)

WEEKLY_STEPS = weekly_step_ids()

STEP_EXTRA_ARGV: dict[str, list[str]] = {
    "evaluate_pending": [],
    "record_daily_run_event": ["--skip-if-unchanged"],
}


def _context_for(ctx: "DailyRunContext | None" = None) -> RuntimeContext:
    """Return the application-resolved context for a sequence operation."""
    return (
        ctx.runtime_context
        if ctx is not None and ctx.runtime_context is not None
        else RuntimeContext.current_context()
    )


def _workspace_for(ctx: "DailyRunContext | None" = None) -> Path:
    return _context_for(ctx).workspace


def _current_for(ctx: "DailyRunContext | None" = None) -> Path:
    context = _context_for(ctx)
    return context.current

STEP_INPUT_ARTIFACTS: dict[str, Callable[["DailyRunContext"], list[str]]] = {
    "neutral_pressure_measurement": lambda ctx: [str(ctx.benchmark_panel_path)],
    "judgment_layer": lambda _ctx: [
        str(_current_for(_ctx) / "neutral_pressure_snapshot.json"),
        str(_context_for(_ctx).surface("hmm_stability") / "hmm_stability_audit.json"),
    ],
    "trade_decision": lambda ctx: [
        str(_context_for(ctx).surface("judgment") / "latest.json"),
        str(_context_for(ctx).surface("judgment") / "promotion_gate.json"),
        str(_current_for(ctx) / "neutral_pressure_snapshot.json"),
        str(_context_for(ctx).surface("hmm_stability") / "hmm_stability_audit.json"),
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
    run_id: str = ""
    plan: CompiledPlan | None = None
    dry_run: bool = False
    runtime_context: RuntimeContext | None = None

    @property
    def force_weekly(self) -> bool:
        return bool(getattr(self.args, "force_weekly", False))

    @property
    def skip_harvester(self) -> bool:
        return bool(getattr(self.args, "skip_harvester", False))

    @property
    def skip_etf(self) -> bool:
        return bool(getattr(self.args, "skip_etf", False))


def should_run_step(step_id: str, step_meta: dict[str, Any], ctx: DailyRunContext) -> tuple[bool, str]:
    skip_flag = step_meta.get("skip_flag")
    if skip_flag == "skip_harvester" and ctx.skip_harvester:
        return False, "skip_harvester"
    if skip_flag == "skip_etf" and ctx.skip_etf:
        return False, "skip_etf"

    status = step_meta.get("status", "active")
    if status in {"archived", "inactive"}:
        return False, f"registry_{status}"

    schedule = step_meta.get("schedule")
    if schedule == "weekly" and not (ctx.force_weekly or ctx.start_time.weekday() == 0):
        return False, "weekly_schedule"

    return True, "run"


def _build_harvester_command(ctx: DailyRunContext) -> list[str]:
    exports_root = _context_for(ctx).data_root / "harvester" / "exports"
    return [
        sys.executable,
        "-m",
        "harvester",
        "--exports-root",
        str(exports_root),
        "daily-release",
    ]


def _build_regime_detection_command(ctx: DailyRunContext) -> list[str]:
    today_str = ctx.start_time.strftime("%Y-%m-%d")
    benchmark_panel = (
        _context_for(ctx).data_root
        / "harvester"
        / "exports"
        / "latest"
        / "data"
        / "benchmark_panel.parquet"
    )
    code = (
        "from pathlib import Path; from ml.regime_detector import detect_regime; "
        "import json; "
        f"result = detect_regime(Path({str(benchmark_panel)!r}), "
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
    "harvester": _build_harvester_command,
    "regime_detection": _build_regime_detection_command,
    "collect_reviews": lambda _ctx: _build_collect_reviews_command(),
}


def build_step_invocation(
    step_id: str, ctx: DailyRunContext, *, plan: CompiledPlan | None = None
) -> tuple[str, list[str] | None, dict[str, str] | None]:
    plan = plan or load_pipeline(_context_for(ctx).paths)
    step = plan.step(step_id)
    mode = step.execution_mode
    env = None

    extra_argv = list(STEP_EXTRA_ARGV.get(step_id, []))
    if step_id == "evaluate_pending":
        extra_argv = _build_evaluate_pending_argv(ctx)

    if step_id in CUSTOM_COMMAND_BUILDERS:
        cmd = CUSTOM_COMMAND_BUILDERS[step_id](ctx) + extra_argv
        return "subprocess", cmd, env

    if mode == "callable":
        command_argv = _command_args(step.command)
        return "callable", command_argv + extra_argv or None, env

    current = step.command
    if not current:
        raise ValueError(f"{step_id} has no execution command")

    cmd = current.split()
    if cmd and cmd[0] == "python":
        cmd[0] = sys.executable
    elif cmd and not Path(cmd[0]).is_absolute() and cmd[0].endswith(".py"):
        cmd = [sys.executable, str(_workspace_for(ctx) / cmd[0])] + cmd[1:]
    cmd.extend(extra_argv)
    return "subprocess", cmd, env


def execute_step(
    step_id: str, ctx: DailyRunContext, *, plan: CompiledPlan | None = None
) -> dict[str, Any]:
    resolved_plan = plan or ctx.plan
    mode, cmd_or_argv, env = build_step_invocation(step_id, ctx, plan=resolved_plan)
    if ctx.dry_run:
        compiled_step = (resolved_plan or load_pipeline(_context_for(ctx).paths)).step(step_id)
        result: dict[str, Any] = {
            "step": step_id,
            "status": "success",
            "mode": "dry_run",
            "execution_mode": mode,
            "duration_s": 0,
        }
        if mode == "callable":
            result["callable"] = compiled_step.callable_spec
            result["argv"] = list(cmd_or_argv or [])
        else:
            result["command"] = list(cmd_or_argv or [])
            result["env_keys"] = sorted((env or {}).keys())
        return result
    if mode == "callable":
        compiled_step = (resolved_plan or load_pipeline(_context_for(ctx).paths)).step(step_id)
        return cast(
            dict[str, Any],
            run_callable_step(step_id, compiled_step.callable_spec, argv=cmd_or_argv),
        )
    assert cmd_or_argv is not None
    return ctx.run_step_fn(step_id, cmd_or_argv, env=env, registry_step=step_id)


def execute_daily_sequence(
    ctx: DailyRunContext, plan: CompiledPlan | None = None
) -> list[dict[str, Any]]:
    """Run all sequence steps that pass schedule/skip/registry gates."""
    plan = plan or load_pipeline(_context_for(ctx).paths)
    ctx.plan = plan
    sequence = plan.sequence()
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

        decision = plan.interpret_failure(step_id, results)
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
                index,
                ctx.total_steps,
                step_id,
                ", ".join(decision.get("degraded_by", [])),
            )

        logger.info("[%d/%d] Running %s...", index, ctx.total_steps, step_id)
        try:
            # Keep the two-argument hook stable for hermetic/operator tests;
            # the context carries the immutable compiled plan for the default
            # implementation.
            result = execute_step(step_id, ctx)
        except ValueError as exc:
            result = {
                "step": step_id,
                "status": "error",
                "error": str(exc),
                "duration_s": 0,
            }

        if degraded and result.get("status") == "success":
            result["degraded"] = True
            result["degraded_by"] = decision.get("degraded_by", [])

        # Shadow migration bridge: expose only a validator-approved chain
        # stamped with this run ID.  Legacy step fields remain authoritative
        # until SYS-21 reader migration is complete.
        attach_output_lineage(
            result,
            plan.step(step_id).outputs,
            run_id=ctx.run_id,
        )

        input_builder = STEP_INPUT_ARTIFACTS.get(step_id)
        input_artifacts = input_builder(ctx) if input_builder else None
        ctx.record_fn(result, input_artifacts=input_artifacts)
        results.append(result)

    return results


class SequenceExecutor:
    """Typed executor that accepts a :class:`CompiledPlan` (WP1B).

    The executor derives its step sequence from the compiled plan rather than
    re-reading and sorting raw YAML.  The existing ``execute_daily_sequence``
    function remains as the internal implementation.
    """

    def execute(self, plan: CompiledPlan, ctx: DailyRunContext) -> list[dict[str, Any]]:
        """Execute the compiled plan's sequence within the given context.

        Args:
            plan: A compiled pipeline (the sole execution authority).
            ctx: Daily run context (step runner, recorder, etc.).
        """
        return execute_daily_sequence(ctx, plan)


__all__ = [
    "CUSTOM_COMMAND_BUILDERS",
    "DailyRunContext",
    "STEP_EXTRA_ARGV",
    "STEP_INPUT_ARTIFACTS",
    "SequenceExecutor",
    "WEEKLY_STEPS",
    "build_step_invocation",
    "execute_daily_sequence",
    "execute_step",
    "should_run_step",
]
