"""Compile and execute the authoritative pipeline specification."""
from __future__ import annotations

import importlib
import inspect
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable

import jsonschema
import yaml

from .paths import WorkspacePaths


class PipelineSpecError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledStep:
    step_id: str
    order: float
    status: str
    owner: str
    schedule: str
    command: str
    callable_spec: str
    execution_mode: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    failure_behavior: str
    affects_core_judgment: bool
    skip_flag: str | None = None

    def as_sequence_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"id": self.step_id}
        if self.schedule != "daily":
            record["schedule"] = self.schedule
        if self.skip_flag:
            record["skip_flag"] = self.skip_flag
        return record


@dataclass(frozen=True)
class CompiledPipeline:
    schema_version: str
    steps: tuple[CompiledStep, ...]
    external_inputs: tuple[str, ...]
    edges: dict[str, tuple[str, ...]]

    def step(self, step_id: str) -> CompiledStep:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(step_id)

    def sequence(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        return [
            step.as_sequence_record()
            for step in self.steps
            if include_archived
            or (
                step.status not in {"archived", "inactive"}
                and step.schedule != "on_demand"
            )
        ]

    def validate(self) -> list[str]:
        errors: list[str] = []
        ids = [step.step_id for step in self.steps]
        if len(ids) != len(set(ids)):
            errors.append("duplicate step ids")
        scheduled_steps = [
            step
            for step in self.steps
            if step.status not in {"archived", "inactive"}
            and step.schedule != "on_demand"
        ]
        orders = [step.order for step in scheduled_steps]
        if len(orders) != len(set(orders)):
            errors.append("duplicate active step order values")
        for step in self.steps:
            if step.schedule not in {"daily", "weekly", "on_demand"}:
                errors.append(f"{step.step_id}: invalid schedule {step.schedule!r}")
            if not step.command and not step.callable_spec and step.status == "active":
                errors.append(f"{step.step_id}: active step has no command/callable")
        sequence_index = {step.step_id: index for index, step in enumerate(self.steps)}
        for consumer, producers in self.edges.items():
            for producer in producers:
                if sequence_index.get(producer, -1) > sequence_index.get(consumer, -1):
                    errors.append(f"{consumer}: runs before producer {producer}")
        return errors


def _paths(step: dict[str, Any], name: str, legacy: str) -> tuple[str, ...]:
    contracts = step.get("contracts") or {}
    values = contracts.get(name)
    if values is None:
        values = step.get(legacy, [])
    if isinstance(values, str):
        values = [values]
    return tuple(str(value).rstrip("/") for value in (values or []) if value)


def _overlaps(producer: str, consumer: str) -> bool:
    return consumer == producer or consumer.startswith(producer + "/")


def load_pipeline(paths: WorkspacePaths | None = None) -> CompiledPipeline:
    paths = paths or WorkspacePaths.discover()
    document = yaml.safe_load(paths.pipeline_spec.read_text(encoding="utf-8")) or {}
    schema_path = paths.root / "protocols/pipeline_spec.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(document, schema)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise PipelineSpecError(f"schema violation at {location}: {exc.message}") from exc
    defaults = document.get("_defaults") or {}
    compiled: list[CompiledStep] = []
    raw_steps = document.get("steps") or {}
    for step_id, raw in raw_steps.items():
        if not isinstance(raw, dict):
            raise PipelineSpecError(f"{step_id}: step must be an object")
        execution = {**(defaults.get("execution") or {}), **(raw.get("execution") or {})}
        authority = raw.get("authority") or {}
        compiled.append(
            CompiledStep(
                step_id=str(step_id),
                order=float(raw.get("order") if raw.get("order") is not None else 9999),
                status=str(raw.get("status", "active")),
                owner=str(raw.get("owner", "")),
                schedule=str(raw.get("schedule", defaults.get("schedule", "daily"))),
                command=str(execution.get("current_command") or raw.get("command") or ""),
                callable_spec=str(execution.get("callable") or execution.get("future_callable") or ""),
                execution_mode=str(execution.get("mode", "subprocess")),
                inputs=_paths(raw, "inputs", "input"),
                outputs=_paths(raw, "outputs", "produces"),
                failure_behavior=str(
                    raw.get("failure_behavior")
                    or authority.get("failure_behavior")
                    or defaults.get("failure_behavior", "continue_with_warning")
                ),
                affects_core_judgment=bool(
                    raw.get("allowed_to_affect_core_judgment")
                    or authority.get("affects_core_judgment")
                ),
                skip_flag=raw.get("skip_flag"),
            )
        )
    compiled.sort(key=lambda step: (step.order, step.step_id))

    edges: dict[str, tuple[str, ...]] = {}
    # On-demand commands are registered entrypoints, not members of the scheduled
    # DAG. Their broad input/output contracts must not impose ordering constraints
    # on the daily/weekly run.
    active_steps = [
        step
        for step in compiled
        if step.status not in {"archived", "inactive"}
        and step.schedule != "on_demand"
    ]
    for consumer in active_steps:
        producers: list[str] = []
        for producer in active_steps:
            if producer.step_id == consumer.step_id:
                continue
            producer_inputs = set(producer.inputs)
            effective_outputs = [path for path in producer.outputs if path not in producer_inputs]
            if any(_overlaps(output, value) for output in effective_outputs for value in consumer.inputs):
                producers.append(producer.step_id)
        if producers:
            edges[consumer.step_id] = tuple(producers)

    pipeline = CompiledPipeline(
        schema_version=str(document.get("schema_version", "")),
        steps=tuple(compiled),
        external_inputs=tuple(str(item).rstrip("/") for item in document.get("external_inputs", [])),
        edges=edges,
    )
    errors = pipeline.validate()
    if errors:
        raise PipelineSpecError("; ".join(errors))
    return pipeline


def resolve_callable(callable_spec: str) -> Callable[..., Any]:
    if ":" not in callable_spec:
        raise ValueError(f"invalid callable spec: {callable_spec}")
    module_name, attribute = callable_spec.split(":", 1)
    module = importlib.import_module(module_name)
    target = getattr(module, attribute)
    if not callable(target):
        raise TypeError(f"{callable_spec} is not callable")
    return target


def run_callable(step: CompiledStep, argv: list[str] | None = None) -> dict[str, Any]:
    start = time.time()
    try:
        target = resolve_callable(step.callable_spec)
        signature = inspect.signature(target)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
        ]
        old_argv = sys.argv[:]
        try:
            if positional and positional[0].name in {"argv", "args"}:
                result = target(list(argv or []))
            else:
                sys.argv = [step.step_id, *(argv or [])]
                result = target()
        finally:
            sys.argv = old_argv
        returncode = result if isinstance(result, int) else 0
        return {
            "step": step.step_id,
            "status": "success" if returncode == 0 else "failed",
            "mode": "callable",
            "callable": step.callable_spec,
            "returncode": returncode,
            "duration_s": round(time.time() - start, 1),
            "stdout_tail": "",
            "stderr_tail": "",
        }
    except Exception as exc:
        return {
            "step": step.step_id,
            "status": "error",
            "mode": "callable",
            "callable": step.callable_spec,
            "error": str(exc),
            "duration_s": round(time.time() - start, 1),
        }


def run_subprocess(
    step: CompiledStep,
    argv: list[str] | None = None,
    *,
    paths: WorkspacePaths | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
) -> dict[str, Any]:
    paths = paths or WorkspacePaths.discover()
    command = shlex.split(step.command)
    if command and command[0] in {"python", "python3"}:
        command[0] = sys.executable
    command.extend(argv or [])
    started = time.time()
    try:
        result = subprocess.run(
            command,
            cwd=paths.root,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "step": step.step_id,
            "status": "success" if result.returncode == 0 else "failed",
            "mode": "subprocess",
            "returncode": result.returncode,
            "duration_s": round(time.time() - started, 1),
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": step.step_id, "status": "timeout", "mode": "subprocess", "duration_s": timeout}
    except Exception as exc:
        return {
            "step": step.step_id,
            "status": "error",
            "mode": "subprocess",
            "error": str(exc),
            "duration_s": round(time.time() - started, 1),
        }


def run_step(
    step_id: str,
    *,
    argv: list[str] | None = None,
    mode: str | None = None,
    paths: WorkspacePaths | None = None,
) -> dict[str, Any]:
    pipeline = load_pipeline(paths)
    step = pipeline.step(step_id)
    resolved_mode = mode or step.execution_mode
    if resolved_mode == "callable":
        return run_callable(step, argv)
    return run_subprocess(step, argv, paths=paths)


def render_sequence_yaml(pipeline: CompiledPipeline) -> str:
    document = {
        "schema_version": "daily_run_sequence.generated.v2",
        "generated_from": "governance/daily_pipeline_registry.yaml",
        "steps": pipeline.sequence(),
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
