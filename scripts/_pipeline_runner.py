"""Pipeline step runner — subprocess and module-callable execution.

Supports the migration described in governance/architecture_cleanup_decisions.md D2.
Registry metadata lives in governance/daily_pipeline_registry.yaml.
"""
from __future__ import annotations

import importlib
import inspect
import os
import subprocess
import sys
import time
from typing import Any, Callable

from _constants import TIMEOUT_LONG
from _runtime_io import ROOT
from _workspace_imports import (
    add_framework_src,
    add_harvester_src,
    add_learning_hub_src,
    add_scripts,
    add_workbench_src,
)

REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def _prepare_import_paths(callable_spec: str) -> None:
    add_scripts()
    if callable_spec.startswith("harvester."):
        add_harvester_src()
    elif callable_spec.startswith("workbench."):
        add_workbench_src()
    elif callable_spec.startswith("system_learning."):
        add_learning_hub_src()
    elif callable_spec.startswith("ml.") or callable_spec.startswith("caselab_runtime."):
        add_framework_src()
        add_workbench_src()
    elif callable_spec.startswith("learning_hub."):
        add_learning_hub_src()
        add_scripts()


def resolve_callable(callable_spec: str) -> Callable[..., Any]:
    """Resolve module:function from registry future_callable metadata."""
    if ":" not in callable_spec:
        raise ValueError(f"invalid callable spec: {callable_spec}")
    module_name, attr_name = callable_spec.split(":", 1)
    _prepare_import_paths(callable_spec)
    module = importlib.import_module(module_name)
    target = getattr(module, attr_name)
    if not callable(target):
        raise TypeError(f"{callable_spec} is not callable")
    return target


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
            result = target()
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
        return {"step": name, "status": "timeout", "mode": "subprocess", "duration_s": 600}
    except Exception as exc:
        return {"step": name, "status": "error", "mode": "subprocess", "error": str(exc), "duration_s": 0}


def load_step_execution(step_id: str) -> dict[str, Any]:
    import yaml

    registry = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    step = registry.get("steps", {}).get(step_id, {})
    return step.get("execution", {})


def run_registry_step(
    step_id: str,
    *,
    argv: list[str] | None = None,
    mode: str | None = None,
    command: list[str] | None = None,
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
    return run_subprocess_step(step_id, cmd)
