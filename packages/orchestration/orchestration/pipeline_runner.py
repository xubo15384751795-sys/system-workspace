"""Pipeline step runner — subprocess and module-callable execution.

Supports the migration described in governance/architecture_cleanup_decisions.md D2.
Registry metadata lives in governance/daily_pipeline_registry.yaml.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import shlex
import subprocess
import sys
import time
from typing import Any, Callable, cast

from scripts._constants import TIMEOUT_LONG
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import (
    load_pipeline,
)
from system_runtime.pipeline import (
    resolve_callable as _resolve_installed_callable,
)

ROOT = WorkspacePaths.discover().root

REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
logger = logging.getLogger(__name__)


def _structured_step_outcome(stdout: str, stderr: str = "") -> dict[str, Any] | None:
    """Read an optional machine-readable step outcome emitted by a command."""
    for stream in (stdout, stderr):
        for line in reversed((stream or "").splitlines()):
            marker = "SYSTEM_STEP_OUTCOME="
            if not line.startswith(marker):
                continue
            try:
                payload = json.loads(line[len(marker):])
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed SYSTEM_STEP_OUTCOME marker")
                continue
            if isinstance(payload, dict):
                return payload
    return None


def _attach_structured_step_outcome(
    result: dict[str, Any], *, stdout: str = "", stderr: str = ""
) -> dict[str, Any]:
    payload = _structured_step_outcome(stdout, stderr)
    if payload is None:
        return result
    result["step_outcome"] = payload
    provider_outcome = payload.get("provider_outcome")
    if isinstance(provider_outcome, dict):
        result["provider_outcome"] = provider_outcome
    if payload.get("status") == "degraded":
        # Degraded means the step completed and downstream work may continue;
        # admission remains responsible for deciding whether it can publish.
        result["degraded"] = True
        reason = payload.get("reason")
        if not reason and isinstance(provider_outcome, dict):
            reason = provider_outcome.get("status")
        result["degraded_reason"] = str(reason or "degraded")
    return result


def resolve_callable(callable_spec: str) -> Callable[..., Any]:
    """Resolve an installed public ``module:function`` entry point."""
    return _resolve_installed_callable(callable_spec)


def _build_argv_for_callable(target: Callable[..., Any], argv: list[str] | None) -> list[Any]:
    if not argv:
        return []
    signature = inspect.signature(target)
    params = [
        p
        for p in signature.parameters.values()
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    if params and params[0].name in {"argv", "args"}:
        return [argv]
    return argv


def run_callable_step(
    name: str,
    callable_spec: str,
    argv: list[str] | None = None,
) -> dict[str, Any]:
    """Execute a pipeline step via direct import."""
    start = time.time()
    try:
        target = resolve_callable(callable_spec)
        signature = inspect.signature(target)
        params = [
            p
            for p in signature.parameters.values()
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        if argv and (not params or params[0].name not in {"argv", "args"}):
            old_argv = sys.argv[:]
            module_name = callable_spec.split(":", 1)[0]
            sys.argv = [module_name.rsplit(".", 1)[-1]] + list(argv)
            try:
                result = target()
            finally:
                sys.argv = old_argv
        elif argv:
            result = target(argv)
        else:
            old_argv = sys.argv[:]
            module_name = callable_spec.split(":", 1)[0]
            sys.argv = [module_name.rsplit(".", 1)[-1]]
            try:
                result = target()
            finally:
                sys.argv = old_argv
        duration = time.time() - start
        returncode = 0
        if isinstance(result, int):
            returncode = result
        status = "success" if returncode == 0 else "failed"
        result = {
            "step": name,
            "status": status,
            "mode": "callable",
            "callable": callable_spec,
            "returncode": returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": "",
            "stderr_tail": "",
        }
        return _attach_structured_step_outcome(result)
    except Exception as exc:
        result = {
            "step": name,
            "status": "error",
            "mode": "callable",
            "callable": callable_spec,
            "error": str(exc),
            "duration_s": round(time.time() - start, 1),
        }
        return result


def run_subprocess_step(
    name: str,
    cmd: list[str],
    env: dict | None = None,
) -> dict[str, Any]:
    """Execute a pipeline step via subprocess (legacy default)."""
    start = time.time()
    merged_env = {**os.environ, **(env or {})}
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"]:
        merged_env.pop(key, None)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_LONG,
            cwd=str(ROOT),
            env=merged_env,
        )
        duration = time.time() - start
        step_result = {
            "step": name,
            "status": "success" if result.returncode == 0 else "failed",
            "mode": "subprocess",
            "returncode": result.returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
            # Full stderr for failed-step log persistence (Phase 0.1). Capped
            # at 256KB by record_step when writing step_logs/<step>.stderr.log.
            "full_stderr": result.stderr or "",
        }
        return _attach_structured_step_outcome(
            step_result,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    except subprocess.TimeoutExpired:
        return {"step": name, "status": "timeout", "mode": "subprocess", "duration_s": TIMEOUT_LONG}
    except Exception as exc:
        return {"step": name, "status": "error", "mode": "subprocess", "error": str(exc), "duration_s": 0}


def load_registry() -> dict[str, Any]:
    import yaml

    return cast(dict[str, Any], yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8")))


def load_step_execution(step_id: str) -> dict[str, Any]:
    """Return compiled execution metadata for compatibility callers."""
    step = load_pipeline(WorkspacePaths(root=ROOT)).step(step_id)
    return {
        "mode": step.execution_mode,
        "current_command": step.command,
        "future_callable": step.callable_spec,
    }


def list_registry_steps(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    """Return pipeline steps from the compiled authoritative plan."""
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    steps: list[dict[str, Any]] = []
    for step in plan.steps:
        if step.status in {"inactive", "archived"} and not include_inactive:
            continue
        steps.append(
            {
                "step_id": step.step_id,
                "order": step.order,
                "status": step.status,
                "owner": step.owner,
                "schedule": step.schedule,
                "command": step.command,
                "affects_core_judgment": step.affects_core_judgment,
                "execution_mode": step.execution_mode,
            }
        )
    return steps


def describe_registry_step(step_id: str) -> dict[str, Any] | None:
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    try:
        step = plan.step(step_id)
    except KeyError:
        return None
    return {
        "step_id": step_id,
        "order": step.order,
        "status": step.status,
        "owner": step.owner,
        "schedule": step.schedule,
        "command": step.command,
        "produces": list(step.outputs),
        "input": list(step.inputs),
        "affects_core_judgment": step.affects_core_judgment,
        "execution": {
            "mode": step.execution_mode,
            "current_command": step.command,
            "future_callable": step.callable_spec,
        },
    }


def run_registry_step(
    step_id: str,
    *,
    argv: list[str] | None = None,
    mode: str | None = None,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a step using the compiled plan's command and callable metadata."""
    step = load_pipeline(WorkspacePaths(root=ROOT)).step(step_id)
    resolved_mode = mode or step.execution_mode
    if resolved_mode == "callable":
        callable_spec = step.callable_spec
        if not callable_spec:
            raise ValueError(f"{step_id} missing execution.future_callable")
        callable_argv = list(argv) if argv is not None else _command_args(step.command)
        return run_callable_step(step_id, callable_spec, argv=callable_argv)

    cmd = command
    if cmd is None:
        current = step.command
        if not current:
            raise ValueError(f"{step_id} missing execution.current_command")
        cmd = current.split()
        if cmd and cmd[0] == "python":
            cmd[0] = sys.executable
        if argv:
            cmd.extend(argv)
    return run_subprocess_step(step_id, cmd, env=env)


def list_profile_steps(profile: str) -> list[str]:
    """Return a compiled execution-profile projection for compatibility callers."""
    plan = load_pipeline(WorkspacePaths(root=ROOT))
    return [step.step_id for step in plan.projection(profile)]


def _command_args(command: str) -> list[str]:
    """Extract registry command flags while discarding interpreter/script tokens."""
    tokens = shlex.split(command or "")
    if not tokens:
        return []
    if tokens[0] in {"python", "python3", sys.executable} and len(tokens) >= 3:
        if tokens[1] == "-m":
            return tokens[3:]
        return tokens[2:]
    return []
