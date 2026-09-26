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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

import jsonschema
import yaml

from .paths import WorkspacePaths
from .registry_authoring import (
    RegistryAuthoringError,
    authoring_source_digest,
    has_authoring_bundle,
    load_authoring_document,
)


class PipelineSpecError(RuntimeError):
    pass


RUNTIME_PLAN_SCHEMA_VERSION = "system.compiled_runtime_plan.v1"
DEFAULT_STEP_TIMEOUT_SECONDS = 1800
ALLOWED_SUBPROCESS_JUSTIFICATIONS = frozenset(
    {
        "real_process_isolation",
        "external_runtime",
        "archive_legacy_executable",
        "security_boundary",
    }
)


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
    artifact_path: str = ""
    ttl_hours: float | None = None
    timeout_seconds: int = DEFAULT_STEP_TIMEOUT_SECONDS
    subprocess_justification: str | None = None

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
    logical_sources: dict[str, Any] = field(default_factory=dict)

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
                    "artifact_path": step.artifact_path,
                    "ttl_hours": step.ttl_hours,
                    "timeout_seconds": step.timeout_seconds,
                    "subprocess_justification": step.subprocess_justification,
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
            if step.timeout_seconds <= 0:
                errors.append(f"{step.step_id}: timeout_seconds must be positive")
            if step.execution_mode == "subprocess":
                justification = step.subprocess_justification
                if not justification:
                    errors.append(
                        f"{step.step_id}: subprocess execution requires an explicit justification"
                    )
                elif justification not in ALLOWED_SUBPROCESS_JUSTIFICATIONS:
                    errors.append(
                        f"{step.step_id}: unsupported subprocess justification {justification!r}"
                    )
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

        # The compiled execution graph must be a DAG before Dagster sees it.
        # Order checks alone do not detect a hand-authored dependency cycle.
        active_id_set = {step.step_id for step in scheduled_steps}
        visit_state: dict[str, int] = {}
        visit_stack: list[str] = []

        def visit(step_id: str) -> None:
            state = visit_state.get(step_id, 0)
            if state == 2:
                return
            if state == 1:
                try:
                    start = visit_stack.index(step_id)
                except ValueError:
                    start = 0
                cycle = " -> ".join((*visit_stack[start:], step_id))
                errors.append(f"pipeline dependency cycle: {cycle}")
                return
            visit_state[step_id] = 1
            visit_stack.append(step_id)
            for producer in self.edges.get(step_id, ()):
                if producer in active_id_set:
                    visit(producer)
            visit_stack.pop()
            visit_state[step_id] = 2

        for step_id in sorted(active_id_set):
            visit(step_id)
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


@dataclass(frozen=True)
class CompiledRuntimePlan:
    """Serializable runtime contract consumed by the single Dagster job.

    ``CompiledPipeline`` remains the typed in-process representation used by
    compatibility callers.  This object is the boundary artifact for a real
    run: it is generated once from the split authoring sources, written into
    the run bundle, and passed to the execution graph without re-reading YAML.
    """

    plan_version: str
    source_digest: str
    source_path: str
    canonical_entrypoint: str
    execution_mode: str
    profile: str
    compiled_plan: CompiledPipeline

    @property
    def plan_digest(self) -> str:
        return self.compiled_plan.plan_digest

    @property
    def selected_steps(self) -> tuple[CompiledStep, ...]:
        if self.profile == "daily":
            selected_ids = tuple(
                str(item["id"])
                for item in self.compiled_plan.sequence()
                if item.get("id")
            )
        else:
            selected_ids = self.compiled_plan.profiles.get(self.profile, ())
        return tuple(self.compiled_plan.step(step_id) for step_id in selected_ids)

    def to_dict(self) -> dict[str, Any]:
        selected = self.selected_steps
        selected_ids = {step.step_id for step in selected}
        edges = {
            consumer: [producer for producer in self.compiled_plan.edges.get(consumer, ()) if producer in selected_ids]
            for consumer in (step.step_id for step in selected)
            if any(producer in selected_ids for producer in self.compiled_plan.edges.get(consumer, ()))
        }
        artifact_contract = {
            step.step_id: {
                "inputs": list(step.inputs),
                "outputs": list(step.outputs),
                "artifact_path": step.artifact_path or None,
                "ttl_hours": step.ttl_hours,
            }
            for step in selected
        }
        step_records = [
            {
                "id": step.step_id,
                "order": step.order,
                "depends_on": list(edges.get(step.step_id, ())),
                "owner": step.owner,
                "schedule": step.schedule,
                "callable": step.callable_spec or None,
                "command": step.command or None,
                "execution_mode": step.execution_mode,
                "timeout_seconds": step.timeout_seconds,
                "failure_policy": step.failure_behavior,
                "subprocess_justification": step.subprocess_justification,
                "artifact_contract": artifact_contract[step.step_id],
            }
            for step in selected
        ]
        return {
            "schema_version": RUNTIME_PLAN_SCHEMA_VERSION,
            "plan_version": self.plan_version,
            "source_digest": self.source_digest,
            "source_path": self.source_path,
            "plan_digest": self.plan_digest,
            "canonical_entrypoint": self.canonical_entrypoint,
            "execution_mode": self.execution_mode,
            "profile": self.profile,
            "step_dag": {
                "nodes": [step.step_id for step in selected],
                "edges": edges,
                "acyclic": True,
            },
            "steps": step_records,
            "timeouts": {step.step_id: step.timeout_seconds for step in selected},
            "failure_policy": {
                step.step_id: step.failure_behavior for step in selected
            },
            "artifact_contract": artifact_contract,
            "ownership": {step.step_id: step.owner for step in selected},
            "schedule": {step.step_id: step.schedule for step in selected},
            "logical_sources": {
                "pipeline_topology": {
                    "nodes": [step.step_id for step in selected],
                    "edges": edges,
                },
                "execution_profile": {
                    "name": self.profile,
                    "steps": [step.step_id for step in selected],
                },
                "monitoring": self.compiled_plan.logical_sources.get("monitoring", {}),
                "freshness": self.compiled_plan.logical_sources.get("freshness", {}),
                "ownership": {step.step_id: step.owner for step in selected},
                "schedule": {step.step_id: step.schedule for step in selected},
            },
        }

    def write(self, target: Path) -> Path:
        """Write the runtime plan atomically and return its resolved path."""
        target = target.expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    @classmethod
    def from_compiled(
        cls,
        compiled_plan: CompiledPipeline,
        *,
        profile: str = "daily",
        source_digest: str = "unknown",
        source_path: str = "unknown",
    ) -> "CompiledRuntimePlan":
        return cls(
            plan_version=f"{profile}.v1",
            source_digest=source_digest,
            source_path=source_path,
            canonical_entrypoint="verity.cli.daily_run:run_daily",
            execution_mode="dagster_generated_plan_job",
            profile=profile,
            compiled_plan=compiled_plan,
        )


def _runtime_source_digest(paths: WorkspacePaths) -> str:
    if has_authoring_bundle(paths.root):
        payload = {
            "pipeline_authoring": authoring_source_digest(paths.root),
            "pipeline_schema": hashlib.sha256(
                (paths.root / "protocols/pipeline_spec.schema.json").read_bytes()
            ).hexdigest(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    payload = {
        "pipeline_registry": hashlib.sha256(paths.pipeline_spec.read_bytes()).hexdigest(),
        "pipeline_schema": hashlib.sha256(
            (paths.root / "protocols/pipeline_spec.schema.json").read_bytes()
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def compile_runtime_plan(
    paths: WorkspacePaths | None = None,
    *,
    profile: str = "daily",
) -> CompiledRuntimePlan:
    """Compile the authoring registry into the single runtime contract."""
    paths = paths or WorkspacePaths.discover()
    compiled = load_pipeline(paths)
    if profile != "daily" and profile not in compiled.profiles:
        raise PipelineSpecError(f"unknown runtime plan profile: {profile}")
    source_path = (
        "governance/pipeline/"
        if has_authoring_bundle(paths.root)
        else str(paths.pipeline_spec.relative_to(paths.root))
    )
    return CompiledRuntimePlan(
        plan_version=f"{profile}.v1",
        source_digest=_runtime_source_digest(paths),
        source_path=source_path,
        canonical_entrypoint="verity.cli.daily_run:run_daily",
        execution_mode="dagster_generated_plan_job",
        profile=profile,
        compiled_plan=compiled,
    )


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
    try:
        document = (
            load_authoring_document(paths.root)
            if has_authoring_bundle(paths.root)
            else yaml.safe_load(paths.pipeline_spec.read_text(encoding="utf-8")) or {}
        )
    except RegistryAuthoringError as exc:
        raise PipelineSpecError(str(exc)) from exc
    schema_path = paths.root / "protocols/pipeline_spec.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(document, schema)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise PipelineSpecError(f"schema violation at {location}: {exc.message}") from exc
    defaults = document.get("_defaults") or {}
    execution_policy = document.get("execution_policy") or {}
    subprocess_justifications = execution_policy.get("subprocess_justifications") or {}
    if not isinstance(subprocess_justifications, dict):
        raise PipelineSpecError("execution_policy.subprocess_justifications must be an object")
    default_timeout_raw = execution_policy.get(
        "default_timeout_seconds",
        (defaults.get("execution") or {}).get(
            "timeout_seconds", DEFAULT_STEP_TIMEOUT_SECONDS
        ),
    )
    try:
        default_timeout_seconds = int(default_timeout_raw)
    except (TypeError, ValueError) as exc:
        raise PipelineSpecError(
            "execution_policy.default_timeout_seconds must be an integer"
        ) from exc
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
        timeout_raw = execution.get(
            "timeout_seconds",
            raw.get("timeout_seconds", default_timeout_seconds),
        )
        try:
            timeout_seconds = int(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise PipelineSpecError(
                f"{step_id}: execution.timeout_seconds must be an integer"
            ) from exc
        ttl_raw = raw.get("ttl_hours", defaults.get("ttl_hours"))
        try:
            ttl_hours = float(ttl_raw) if ttl_raw is not None else None
        except (TypeError, ValueError) as exc:
            raise PipelineSpecError(f"{step_id}: ttl_hours must be numeric") from exc
        raw_justification = (
            execution.get("subprocess_justification")
            or raw.get("subprocess_justification")
            or subprocess_justifications.get(str(step_id))
        )
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
                artifact_path=str(raw.get("artifact_path") or ""),
                ttl_hours=ttl_hours,
                timeout_seconds=timeout_seconds,
                subprocess_justification=(
                    str(raw_justification).strip() if raw_justification else None
                ),
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
        logical_sources={
            "monitoring": {
                "contracts": document.get("monitoring_contracts") or {},
                "classification": document.get("monitoring_classification") or {},
            },
            "freshness": document.get("content_freshness") or {},
            "ownership": {
                str(step_id): str(
                    (raw.get("owner") or (raw.get("authority") or {}).get("owner") or "")
                )
                for step_id, raw in raw_steps.items()
                if isinstance(raw, dict)
            },
            "schedule": {
                str(step_id): str(raw.get("schedule", defaults.get("schedule", "daily")))
                for step_id, raw in raw_steps.items()
                if isinstance(raw, dict)
            },
            "execution_profile": document.get("execution_profiles") or {},
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
    timeout: int | None = None,
) -> dict[str, Any]:
    paths = paths or WorkspacePaths.discover()
    effective_timeout = int(timeout or step.timeout_seconds)
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
            timeout=effective_timeout,
        )
        return {
            "step": step.step_id,
            "status": "success" if result.returncode == 0 else "failed",
            "mode": "subprocess",
            "returncode": result.returncode,
            "duration_s": round(time.time() - started, 1),
            "timeout_seconds": effective_timeout,
            "subprocess_justification": step.subprocess_justification,
            "stdout_tail": result.stdout[-500:] if result.stdout else "",
            "stderr_tail": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "step": step.step_id,
            "status": "timeout",
            "mode": "subprocess",
            "duration_s": effective_timeout,
            "timeout_seconds": effective_timeout,
            "subprocess_justification": step.subprocess_justification,
        }
    except Exception as exc:
        return {
            "step": step.step_id,
            "status": "error",
            "mode": "subprocess",
            "error": str(exc),
            "duration_s": round(time.time() - started, 1),
            "timeout_seconds": effective_timeout,
            "subprocess_justification": step.subprocess_justification,
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
        "generated_from": "governance/pipeline/*.yaml",
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
