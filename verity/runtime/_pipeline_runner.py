"""Compatibility import surface for the Orchestration pipeline runner."""
from __future__ import annotations

from typing import Any

from orchestration import pipeline_runner as _impl
from orchestration.pipeline_runner import (
    describe_registry_step,
    list_profile_steps,
    list_registry_steps,
    load_registry,
    load_step_execution,
    resolve_callable,
)

run_callable_step = _impl.run_callable_step
run_subprocess_step = _impl.run_subprocess_step


def run_registry_step(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Delegate while preserving monkeypatch compatibility for old callers."""
    original_callable = _impl.run_callable_step
    original_subprocess = _impl.run_subprocess_step
    _impl.run_callable_step = run_callable_step
    _impl.run_subprocess_step = run_subprocess_step
    try:
        return _impl.run_registry_step(*args, **kwargs)
    finally:
        _impl.run_callable_step = original_callable
        _impl.run_subprocess_step = original_subprocess


__all__ = [
    "describe_registry_step",
    "list_profile_steps",
    "list_registry_steps",
    "load_registry",
    "load_step_execution",
    "resolve_callable",
    "run_callable_step",
    "run_registry_step",
    "run_subprocess_step",
]
