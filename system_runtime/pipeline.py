"""Compile and execute the authoritative pipeline specification."""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable, cast

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
    depends_on: tuple[str, ...] = ()
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
    profiles: dict[str, tuple[str, ...]]

    def step(self, step_id: str) -> CompiledStep:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise KeyError(step_id)

    def projection(self, profile: str) -> tuple[CompiledStep, ...]:
        """Return an execution-mode projection owned by the compiled plan."""
        try:
            step_ids = self.profiles[profile]
        except KeyError as exc:
            raise KeyError(f"unknown pipeline execution profile: {profile}") from exc
        return tuple(self.step(step_id) for step_id in step_ids)

    @property
    def plan_digest(self) -> str:
        """Stable identity for this compiled plan and its execution edges."""
        payload = {
            "schema_version": self.schema_version,
            "steps": [
                {
                    "id": step.step_id,
                    "order": step.order,
                    "status": step.status,
                    "schedule": step.schedule,
                    "command": step.command,
                    "callable": step.callable_spec,
                    "mode": step.execution_mode,
                    "inputs": list(step.inputs),
                    "outputs": list(step.outputs),
                    "failure_behavior": step.failure_behavior,
                    "affects_core_judgment": step.affects_core_judgment,
                    "depends_on": list(step.depends_on),
                    "skip_flag": step.skip_flag,
                }
                for step in self.steps
            ],
            "edges": {key: list(value) for key, value in sorted(self.edges.items())},
            "profiles": {key: list(value) for key, value in sorted(self.profiles.items())},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

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
        active_ids = {
            step.step_id
            for step in self.steps
            if step.status not in {"archived", "inactive"}
        }
        for step in self.steps:
            if len(step.depends_on) != len(set(step.depends_on)):
                errors.append(f"{step.step_id}: duplicate depends_on entries")
            for producer in step.depends_on:
                if producer == step.step_id:
                    errors.append(f"{step.step_id}: depends_on itself")
                elif producer not in active_ids:
                    errors.append(f"{step.step_id}: depends_on inactive/unknown {producer}")
        for consumer, producers in self.edges.items():
            for producer in producers:
                if sequence_index.get(producer, -1) > sequence_index.get(consumer, -1):
                    errors.append(f"{consumer}: runs before producer {producer}")
        for profile, step_ids in self.profiles.items():
            if len(step_ids) != len(set(step_ids)):
                errors.append(f"{profile}: duplicate step ids")
            for step_id in step_ids:
                try:
                    step = self.step(step_id)
                except KeyError:
                    errors.append(f"{profile}: unknown step {step_id}")
                    continue
                if step.status in {"archived", "inactive"}:
                    errors.append(f"{profile}: archived/inactive step {step_id}")
        return errors

    def interpret_failure(self, step_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Interpret upstream failures using this plan's edges and metadata."""
        status_by_step = {result.get("step"): result.get("status") for result in results}
        blocked_by: list[str] = []
        degraded_by: list[str] = []
        for producer in self.edges.get(step_id, ()):
            status = status_by_step.get(producer)
            if status is None or status == "success":
                continue
            behavior = self.step(producer).failure_behavior
            if behavior in {
                "block_current_readout",
                "block_core_judgment",
                "block_promotion",
                "decision_adjacent_block",
            }:
                blocked_by.append(producer)
            elif behavior in {"hold_flat", "lower_claim_ceiling"}:
                degraded_by.append(producer)
        if blocked_by:
            action = "block"
        elif degraded_by:
            action = "run_degraded"
        else:
            action = "run"
        return {
            "action": action,
            "blocked_by": blocked_by,
            "behavior": self.step(step_id).failure_behavior,
            "degraded": bool(degraded_by),
            "degraded_by": degraded_by,
        }


# WP1B: ``CompiledPlan`` is the canonical name for the compiled pipeline that
# the executor accepts.  It is an alias for ``CompiledPipeline`` so existing
# code that references ``CompiledPipeline`` continues to work.
CompiledPlan = CompiledPipeline


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
        raw_dependencies = raw.get("depends_on")
        if raw_dependencies is None:
            dependencies: tuple[str, ...] = ()
        elif isinstance(raw_dependencies, list) and all(
            isinstance(item, str) and item for item in raw_dependencies
        ):
            dependencies = tuple(raw_dependencies)
        else:
            raise PipelineSpecError(f"{step_id}: depends_on must be a list of non-empty strings")
        raw_order = raw.get("order")
        order = float(str(raw_order)) if raw_order is not None else 9999.0
        compiled.append(
            CompiledStep(
                step_id=str(step_id),
                order=order,
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
                depends_on=dependencies,
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
        if consumer.depends_on:
            edges[consumer.step_id] = consumer.depends_on
            continue
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
        profiles={
            str(profile): tuple(str(step_id) for step_id in step_ids)
            for profile, step_ids in (document.get("execution_profiles") or {}).items()
        },
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
    return cast(Callable[..., Any], target)


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
    return cast(str, yaml.safe_dump(document, sort_keys=False, allow_unicode=True))


def validate_pipeline_docs(paths: WorkspacePaths, pipeline: CompiledPipeline) -> list[str]:
    """Validate that human-facing pipeline docs preserve authority boundaries.

    ``pipeline_schedule.md`` is intentionally a historical reference rather
    than an executable schedule. This check prevents it, README, or the layout
    map from silently becoming a second runtime authority or from describing
    the retired submodule layout as the current checkout.
    """

    required: dict[str, tuple[str, ...]] = {
        "README.md": (
            "Repository Layout (monorepo workspace)",
            "packages/orchestration/",
        ),
        "governance/repo_layout_map.md": (
            "Current canonical workspace",
            "Historical pre-consolidation layout",
            "packages/orchestration/",
            "entrypoint_registry.yaml",
        ),
        "governance/pipeline_schedule.md": (
            "Historical Daily / Weekly / On-Demand Reference",
            "Current executable authority:",
            "governance/daily_pipeline_registry.yaml",
            "governance/daily_run_sequence.yaml",
        ),
    }
    errors: list[str] = []
    for relative, markers in required.items():
        path = paths.root / relative
        if not path.exists():
            errors.append(f"missing documentation: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in text:
                errors.append(f"{relative}: missing marker {marker!r}")

    readme_path = paths.root / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")
        if "git clone --recurse-submodules" in readme:
            errors.append("README.md: retired recursive-submodule clone command remains")
        if ".gitmodules" not in readme:
            errors.append("README.md: absence of .gitmodules is not stated")

    schedule_path = paths.root / "governance/pipeline_schedule.md"
    if schedule_path.exists():
        schedule = schedule_path.read_text(encoding="utf-8")
        if "not\n> current runtime authority" not in schedule:
            errors.append("pipeline_schedule.md: historical non-authority boundary is missing")

    if not (paths.root / ".gitmodules").exists() and any(
        "git submodule" in (paths.root / relative).read_text(encoding="utf-8")
        for relative in ("README.md",)
        if (paths.root / relative).exists()
    ):
        # README may mention submodules only in the explicit absence statement;
        # this branch catches an accidental operational instruction instead.
        readme = readme_path.read_text(encoding="utf-8")
        operational = ("submodule update", "--recurse-submodules")
        if any(marker in readme for marker in operational):
            errors.append("README.md: operational submodule instruction remains")

    # Consume the compiled plan so the CLI reports a validator tied to the
    # same active graph as execution, rather than merely linting prose.
    if not pipeline.steps:
        errors.append("compiled pipeline has no active steps")
    return errors
