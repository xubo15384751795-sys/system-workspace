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

from _daily_run_sequence import load_daily_run_sequence, weekly_step_ids
from _pipeline_runner import load_registry, load_step_execution, run_registry_step
from _runtime_io import ROOT, current_dir

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
            str(ROOT / "Workbench" / "src"),
            str(ROOT / "deformation-framework" / "src"),
        ]),
    }


def _harvester_env() -> dict[str, str]:
    return {"PYTHONPATH": str(ROOT / "structural-risk-harvester" / "src")}


def _workbench_env() -> dict[str, str]:
    return {"PYTHONPATH": str(ROOT / "Workbench" / "src")}


def _policy_env() -> dict[str, str]:
    return {"PYTHONPATH": f"{ROOT}:{ROOT / 'Workbench' / 'src'}:{ROOT / 'scripts'}"}


STEP_ENV: dict[str, Callable[[], dict[str, str]]] = {
    "harvester": _harvester_env,
    "structural_replay": _replay_env,
    "regime_detection": _workbench_env,
    "build_policy_from_paper": _policy_env,
}

STEP_INPUT_ARTIFACTS: dict[str, Callable[["DailyRunContext"], list[str]]] = {
    "structural_replay": lambda ctx: [str(ctx.benchmark_panel_path)],
    "bridge": lambda _ctx: [
        str(ROOT / "Output" / "sandbox" / "structural_replay_v2" / "framework_output.json"),
    ],
    "judgment_layer": lambda _ctx: [
        str(current_dir() / "framework_output.json"),
        str(ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"),
        str(ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"),
        str(ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"),
    ],
    "trade_decision": lambda _ctx: [
        str(ROOT / "Output" / "judgment" / "latest.json"),
        str(ROOT / "Output" / "judgment" / "promotion_gate.json"),
        str(ROOT / "Output" / "k_measurement" / "k_measurement_gate.json"),
        str(ROOT / "Output" / "x_measurement" / "x_measurement_gate.json"),
        str(ROOT / "Output" / "hmm_stability" / "hmm_stability_audit.json"),
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


def _build_structural_replay_command(ctx: DailyRunContext) -> list[str]:
    release_id = "latest"
    catalog_path = ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
    if catalog_path.exists():
        try:
            import json

            cat = json.loads(catalog_path.read_text(encoding="utf-8"))
            release_id = cat.get("release_id", "latest")
        except Exception:
            logger.debug("Failed to read harvester catalog release_id", exc_info=True)
    return [
        sys.executable,
        str(ROOT / "scripts" / "structural_replay_v2.py"),
        f"panel.release_id={release_id}",
        f"panel.path={ctx.benchmark_panel_path}",
        f"run.tag=daily_{ctx.start_time.strftime('%Y%m%d')}",
        f"run.as_of_date={ctx.start_time.strftime('%Y-%m-%d')}",
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
    "structural_replay": _build_structural_replay_command,
    "regime_detection": _build_regime_detection_command,
    "collect_reviews": lambda _ctx: _build_collect_reviews_command(),
}


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
        return "subprocess", CUSTOM_COMMAND_BUILDERS[step_id](ctx) + extra_argv, env

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
    return "subprocess", cmd, env


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

        input_builder = STEP_INPUT_ARTIFACTS.get(step_id)
        input_artifacts = input_builder(ctx) if input_builder else None
        ctx.record_fn(result, input_artifacts=input_artifacts)
        results.append(result)

    return results
