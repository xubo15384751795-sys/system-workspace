"""Side-effect-free plan/apply contract for the compiled System pipeline.

The plan phase describes policy and declared contracts only.  It must not
pretend to know future provider bytes and it must not write ``Data/`` or
``Output/``.  A later apply preflight binds a saved plan to an evidence
manifest and a serialized publish-admission token; stale plans or mismatched
digests fail closed before any execution or pointer mutation can occur.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .paths import WorkspacePaths
from .pipeline import CompiledPlan, load_pipeline

PLAN_SCHEMA_VERSION = "system.plan.v1"
EVIDENCE_SCHEMA_VERSION = "system.evidence.v1"
PLAN_STORAGE_DIR = ".system/plans"

_CONTRACT_POLICY_PATHS = (
    # Keep the generated compatibility view in the plan fingerprint so legacy
    # workspaces that only carry this file still invalidate saved plans.  The
    # default runtime authority remains the split sources below.
    "governance/daily_pipeline_registry.yaml",
    "governance/pipeline/topology.yaml",
    "governance/pipeline/execution_profiles.yaml",
    "governance/pipeline/monitoring.yaml",
    "governance/pipeline/freshness.yaml",
    "governance/pipeline/ownership.yaml",
    "governance/pipeline/schedule_metadata.yaml",
    "protocols/pipeline_spec.schema.json",
    "governance/output_routing_policy.yaml",
    "governance/system_constitution.yaml",
)
_CONTRACT_CODE_PATHS = (
    "system_runtime/pipeline.py",
    "system_runtime/registry_authoring.py",
    "system_runtime/plan_apply.py",
    "system_runtime/publish_admission.py",
    "system_runtime/publish_transaction.py",
    "packages/orchestration/orchestration/sequence_executor.py",
    "packages/orchestration/orchestration/runner.py",
)


class PlanApplyError(RuntimeError):
    """Raised when a plan or apply preflight cannot be trusted."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_digest(path: Path) -> str:
    if not path.is_file():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path_digest(root: Path, relative_paths: tuple[str, ...]) -> str:
    payload = {
        relative: _file_digest(root / relative)
        for relative in relative_paths
    }
    return _digest(payload)


def _code_sha(root: Path) -> str:
    configured = os.environ.get("SYSTEM_CODE_SHA", "").strip()
    if configured:
        return configured
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _profile_steps(plan: CompiledPlan, profile: str) -> tuple[str, ...]:
    if profile == "daily":
        return tuple(
            str(item["id"])
            for item in plan.sequence()
            if item.get("id")
        )
    return tuple(step.step_id for step in plan.projection(profile))


def _profile_edges(plan: CompiledPlan, step_ids: tuple[str, ...]) -> dict[str, list[str]]:
    selected = set(step_ids)
    return {
        consumer: [producer for producer in producers if producer in selected]
        for consumer, producers in sorted(plan.edges.items())
        if consumer in selected and any(producer in selected for producer in producers)
    }


@dataclass(frozen=True)
class PlanArtifact:
    """Immutable description of policy and declared inputs for one profile."""

    plan_id: str
    schema_version: str
    profile: str
    created_at: str
    code_sha: str
    plan_digest: str
    policy_digest: str
    code_digest: str
    input_contract_digest: str
    steps: tuple[str, ...]
    edges: dict[str, tuple[str, ...]]

    def identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "code_sha": self.code_sha,
            "plan_digest": self.plan_digest,
            "policy_digest": self.policy_digest,
            "code_digest": self.code_digest,
            "input_contract_digest": self.input_contract_digest,
            "steps": list(self.steps),
            "edges": {key: list(value) for key, value in sorted(self.edges.items())},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "profile": self.profile,
            "created_at": self.created_at,
            **self.identity_payload(),
        }


def build_plan(
    paths: WorkspacePaths,
    *,
    profile: str = "daily",
    code_sha: str | None = None,
) -> PlanArtifact:
    """Compile a plan without writing to the workspace."""
    compiled = load_pipeline(paths)
    steps = _profile_steps(compiled, profile)
    selected = [compiled.step(step_id) for step_id in steps]
    input_contract = {
        "external_inputs": list(compiled.external_inputs),
        "steps": {
            step.step_id: {
                "inputs": list(step.inputs),
                "outputs": list(step.outputs),
                "failure_behavior": step.failure_behavior,
                "affects_core_judgment": step.affects_core_judgment,
            }
            for step in selected
        },
    }
    identity = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "profile": profile,
        "code_sha": code_sha or _code_sha(paths.root),
        "plan_digest": compiled.plan_digest,
        "policy_digest": _path_digest(paths.root, _CONTRACT_POLICY_PATHS),
        "code_digest": _path_digest(paths.root, _CONTRACT_CODE_PATHS),
        "input_contract_digest": _digest(input_contract),
        "steps": list(steps),
        "edges": _profile_edges(compiled, steps),
    }
    return PlanArtifact(
        plan_id=_digest(identity),
        schema_version=PLAN_SCHEMA_VERSION,
        profile=profile,
        created_at=datetime.now(timezone.utc).isoformat(),
        code_sha=str(identity["code_sha"]),
        plan_digest=str(identity["plan_digest"]),
        policy_digest=str(identity["policy_digest"]),
        code_digest=str(identity["code_digest"]),
        input_contract_digest=str(identity["input_contract_digest"]),
        steps=steps,
        edges={
            key: tuple(value)
            for key, value in cast(dict[str, list[str]], identity["edges"]).items()
        },
    )


def _assert_safe_plan_path(root: Path, path: Path) -> Path:
    target = path.expanduser().resolve()
    forbidden = (root / "Data").resolve(), (root / "Output").resolve()
    if any(target == base or base in target.parents for base in forbidden):
        raise PlanApplyError("plan artifacts may not be written below Data/ or Output/")
    return target


def default_plan_path(root: Path, plan_id: str) -> Path:
    return root / PLAN_STORAGE_DIR / f"{plan_id}.json"


def write_plan(artifact: PlanArtifact, path: Path, *, root: Path) -> Path:
    """Persist a plan only to an explicit non-Data/non-Output path."""
    target = _assert_safe_plan_path(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(
        json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise PlanApplyError(f"plan field {key!r} is missing")
    return value


def load_plan(path: Path) -> PlanArtifact:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanApplyError(f"cannot read plan: {path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise PlanApplyError(f"unsupported or invalid plan schema: {path}")
    edges_raw = payload.get("edges")
    steps_raw = payload.get("steps")
    if not isinstance(steps_raw, list) or not all(isinstance(item, str) for item in steps_raw):
        raise PlanApplyError("plan steps must be a list of strings")
    if not isinstance(edges_raw, dict):
        raise PlanApplyError("plan edges must be an object")
    edges: dict[str, tuple[str, ...]] = {}
    for consumer, producers in edges_raw.items():
        if not isinstance(consumer, str) or not isinstance(producers, list):
            raise PlanApplyError("plan edges must map step IDs to string lists")
        if not all(isinstance(item, str) for item in producers):
            raise PlanApplyError("plan edges must map step IDs to string lists")
        edges[consumer] = tuple(producers)
    artifact = PlanArtifact(
        plan_id=_require_string(payload, "plan_id"),
        schema_version=PLAN_SCHEMA_VERSION,
        profile=_require_string(payload, "profile"),
        created_at=_require_string(payload, "created_at"),
        code_sha=_require_string(payload, "code_sha"),
        plan_digest=_require_string(payload, "plan_digest"),
        policy_digest=_require_string(payload, "policy_digest"),
        code_digest=_require_string(payload, "code_digest"),
        input_contract_digest=_require_string(payload, "input_contract_digest"),
        steps=tuple(steps_raw),
        edges=edges,
    )
    if _digest(artifact.identity_payload()) != artifact.plan_id:
        raise PlanApplyError("plan_id does not match the plan contents")
    return artifact


def validate_plan(artifact: PlanArtifact, paths: WorkspacePaths) -> dict[str, Any]:
    """Compare a saved plan with the current policy/code/compiled plan."""
    current = build_plan(paths, profile=artifact.profile, code_sha=artifact.code_sha)
    differences: list[str] = []
    for field in (
        "plan_digest",
        "policy_digest",
        "code_digest",
        "input_contract_digest",
        "steps",
        "edges",
    ):
        if getattr(artifact, field) != getattr(current, field):
            differences.append(field)
    return {
        "stale": bool(differences),
        "differences": differences,
        "plan_id": artifact.plan_id,
        "current_plan_id": current.plan_id,
        "plan_digest": artifact.plan_digest,
        "current_plan_digest": current.plan_digest,
        "profile": artifact.profile,
    }


def _evidence_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanApplyError(f"evidence manifest must be JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PlanApplyError("evidence manifest must contain a JSON object")
    return payload


def evidence_digest(path: Path) -> str:
    """Digest evidence content, excluding an optional self-reported digest."""
    payload = _evidence_payload(path)
    body = {key: value for key, value in payload.items() if key != "evidence_digest"}
    actual = _digest(body)
    declared = payload.get("evidence_digest")
    if declared is not None and declared != actual:
        raise PlanApplyError("evidence_digest does not match the evidence manifest")
    return actual


def _admission_digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "admission_digest"}
    return _digest(body)


def validate_apply(
    artifact: PlanArtifact,
    paths: WorkspacePaths,
    *,
    evidence_path: Path,
    admission_path: Path,
) -> dict[str, Any]:
    """Run a no-write apply preflight bound to evidence and admission."""
    current = validate_plan(artifact, paths)
    if current["stale"]:
        raise PlanApplyError(
            "stale plan rejected: " + ", ".join(current["differences"])
        )
    evidence = _evidence_payload(evidence_path)
    actual_evidence_digest = evidence_digest(evidence_path)
    if evidence.get("plan_digest") != artifact.plan_digest:
        raise PlanApplyError("evidence plan_digest does not match the saved plan")
    try:
        admission = json.loads(admission_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanApplyError(f"admission token must be JSON: {admission_path}: {exc}") from exc
    if not isinstance(admission, dict):
        raise PlanApplyError("admission token must contain a JSON object")
    if admission.get("admission_digest") != _admission_digest(admission):
        raise PlanApplyError("admission_digest does not match the admission token")
    if admission.get("plan_digest") != artifact.plan_digest:
        raise PlanApplyError("admission plan_digest does not match the saved plan")
    if admission.get("evidence_digest") != actual_evidence_digest:
        raise PlanApplyError("admission evidence_digest does not match the evidence manifest")
    if admission.get("integrity_verdict") != "PASS":
        raise PlanApplyError("apply requires integrity_verdict=PASS")
    if admission.get("diagnostic_verdict", admission.get("diagnostic_publish_verdict")) != "PASS":
        raise PlanApplyError("apply requires diagnostic publish verdict PASS")
    return {
        "status": "READY",
        "would_write": False,
        "plan_id": artifact.plan_id,
        "plan_digest": artifact.plan_digest,
        "evidence_digest": actual_evidence_digest,
        "admission_digest": admission["admission_digest"],
        "authority_verdict": admission.get("authority_verdict", admission.get("decision_authority_verdict")),
    }


def resolve_plan_reference(reference: str, *, root: Path) -> Path:
    candidate = Path(reference).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_file():
        return candidate.resolve()
    stored = default_plan_path(root, reference)
    if stored.is_file():
        return stored.resolve()
    raise PlanApplyError(f"plan not found: {reference}")


__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "PLAN_SCHEMA_VERSION",
    "PlanApplyError",
    "PlanArtifact",
    "build_plan",
    "default_plan_path",
    "evidence_digest",
    "load_plan",
    "resolve_plan_reference",
    "validate_apply",
    "validate_plan",
    "write_plan",
]
