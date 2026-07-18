"""Pipeline step runner — subprocess and module-callable execution.

Supports the migration described in governance/architecture_cleanup_decisions.md D2.
Registry metadata lives in governance/daily_pipeline_registry.yaml.
"""
from __future__ import annotations

import inspect
import os
import subprocess
import sys
import time
from typing import Any, Callable

from scripts._constants import TIMEOUT_LONG
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import resolve_callable as _resolve_installed_callable

ROOT = WorkspacePaths.discover().root

REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def resolve_callable(callable_spec: str) -> Callable[..., Any]:
    """Resolve an installed public ``module:function`` entry point."""
    return _resolve_installed_callable(callable_spec)


def _build_argv_for_callable(target: Callable[..., Any], argv: list[str] | None) -> list[str]:
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
        return {
            "step": name,
            "status": status,
            "mode": "callable",
            "callable": callable_spec,
            "returncode": returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": "",
            "stderr_tail": "",
        }
    except Exception as exc:
        return {
            "step": name,
            "status": "error",
            "mode": "callable",
            "callable": callable_spec,
            "error": str(exc),
            "duration_s": round(time.time() - start, 1),
        }


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
        return {
            "step": name,
            "status": "success" if result.returncode == 0 else "failed",
            "mode": "subprocess",
            "returncode": result.returncode,
            "duration_s": round(duration, 1),
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": name, "status": "timeout", "mode": "subprocess", "duration_s": TIMEOUT_LONG}
    except Exception as exc:
        return {"step": name, "status": "error", "mode": "subprocess", "error": str(exc), "duration_s": 0}


def load_registry() -> dict[str, Any]:
    import yaml

    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def load_step_execution(step_id: str) -> dict[str, Any]:
    registry = load_registry()
    step = registry.get("steps", {}).get(step_id, {})
    return step.get("execution", {})


def list_registry_steps(*, include_inactive: bool = False) -> list[dict[str, Any]]:
    """Return pipeline steps from daily_pipeline_registry.yaml."""
    registry = load_registry()
    steps: list[dict[str, Any]] = []
    for step_id, step in registry.get("steps", {}).items():
        if not isinstance(step, dict):
            continue
        if step.get("status") == "inactive" and not include_inactive:
            continue
        steps.append(
            {
                "step_id": step_id,
                "order": step.get("order", 9999),
                "status": step.get("status", "unknown"),
                "owner": step.get("owner", ""),
                "schedule": step.get("schedule", "daily"),
                "command": step.get("command", ""),
                "affects_core_judgment": bool(
                    step.get("allowed_to_affect_core_judgment")
                    or (step.get("authority") or {}).get("affects_core_judgment")
                ),
                "execution_mode": (step.get("execution") or {}).get("mode", "subprocess"),
            }
        )
    steps.sort(key=lambda item: (item["order"] if item["order"] is not None else 9999, item["step_id"]))
    return steps


def describe_registry_step(step_id: str) -> dict[str, Any] | None:
    registry = load_registry()
    step = registry.get("steps", {}).get(step_id)
    if not isinstance(step, dict):
        return None
    execution = step.get("execution", {})
    return {
        "step_id": step_id,
        "order": step.get("order"),
        "status": step.get("status"),
        "owner": step.get("owner"),
        "schedule": step.get("schedule", "daily"),
        "command": step.get("command"),
        "produces": step.get("produces", []),
        "input": step.get("input", []),
        "affects_core_judgment": bool(
            step.get("allowed_to_affect_core_judgment")
            or (step.get("authority") or {}).get("affects_core_judgment")
        ),
        "execution": execution,
    }


def run_registry_step(
    step_id: str,
    *,
    argv: list[str] | None = None,
    mode: str | None = None,
    command: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a registry step using subprocess or callable mode."""
    execution = load_step_execution(step_id)
    resolved_mode = mode or execution.get("mode", "subprocess")
    if resolved_mode == "callable":
        callable_spec = execution.get("future_callable", "")
        if not callable_spec:
            raise ValueError(f"{step_id} missing execution.future_callable")
        return run_callable_step(step_id, callable_spec, argv=argv)

    cmd = command
    if cmd is None:
        current = execution.get("current_command", "")
        if not current:
            raise ValueError(f"{step_id} missing execution.current_command")
        cmd = current.split()
        if cmd and cmd[0] == "python":
            cmd[0] = sys.executable
    return run_subprocess_step(step_id, cmd, env=env)
