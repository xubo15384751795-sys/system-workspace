"""Engine-neutral Experiment Protocol helpers.

The protocol is the boundary between System research intent and an external
experiment engine.  It validates the specification/result pair, computes the
spec fingerprint used for provenance, and wraps raw adapter metrics without
granting judgment or publication authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from numbers import Real
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
import yaml
from workbench.paths import workspace_root as _workspace_root


ROOT = _workspace_root()
SPEC_SCHEMA_PATH = ROOT / "protocols" / "experiment_spec.schema.json"
RESULT_SCHEMA_PATH = ROOT / "protocols" / "experiment_result.schema.json"
REGISTRY_SCHEMA_PATH = ROOT / "protocols" / "experiment_registry.schema.json"
REGISTRY_PATH = ROOT / "governance" / "experiment_registry.yaml"


class ExperimentProtocolError(ValueError):
    """Raised when an experiment protocol payload is invalid."""


def validate_spec(spec: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation messages for an Experiment Spec."""
    return _validate(spec, SPEC_SCHEMA_PATH)


def validate_result(result: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation messages for a Result Artifact."""
    return _validate(result, RESULT_SCHEMA_PATH)


def validate_registry(registry: Mapping[str, Any]) -> list[str]:
    """Return deterministic validation messages for the adapter registry."""
    return _validate(registry, REGISTRY_SCHEMA_PATH)


def load_registry(path: str | Path = REGISTRY_PATH) -> dict[str, Any]:
    """Load and validate the YAML adapter registry from disk."""
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExperimentProtocolError(f"Cannot load experiment registry {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExperimentProtocolError(f"Experiment registry {path} must contain an object")
    errors = validate_registry(payload)
    if errors:
        raise ExperimentProtocolError("Invalid Experiment Registry: " + "; ".join(errors))
    return payload


def load_spec(path: str | Path) -> dict[str, Any]:
    """Load and validate a JSON Experiment Spec from disk."""
    payload = _load_json(path)
    errors = validate_spec(payload)
    if errors:
        raise ExperimentProtocolError("Invalid Experiment Spec: " + "; ".join(errors))
    return payload


def spec_sha256(spec: Mapping[str, Any]) -> str:
    """Fingerprint a validated spec using canonical JSON encoding."""
    errors = validate_spec(spec)
    if errors:
        raise ExperimentProtocolError("Cannot fingerprint invalid Experiment Spec: " + "; ".join(errors))
    encoded = json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_result_artifact(
    spec: Mapping[str, Any],
    raw_metrics: Mapping[str, Mapping[str, Any]],
    *,
    engine_version: str | None = None,
    input_artifacts: Sequence[Mapping[str, Any]] = (),
    limitations: Sequence[str] = (),
    feedback_type: str | None = None,
) -> dict[str, Any]:
    """Wrap adapter metrics as a governance-safe Experiment Result Artifact.

    The function deliberately treats executor diagnostics as first-class
    state.  A blocked treatment is an inconclusive experiment, never a zero
    delta and never a promotion candidate.
    """
    spec_errors = validate_spec(spec)
    if spec_errors:
        raise ExperimentProtocolError("Cannot build result from invalid spec: " + "; ".join(spec_errors))

    runs: list[dict[str, Any]] = []
    blocked_reasons: list[str] = []
    model_ids_by_role = {
        str(model.get("role")): str(model.get("model_id"))
        for model in spec.get("models", [])
        if model.get("role") and model.get("model_id")
    }
    for fallback_id, raw in raw_metrics.items():
        if not isinstance(raw, Mapping):
            blocked_reasons.append(f"invalid_metrics:{fallback_id}")
            continue
        blocked = bool(raw.get("feedback_blocked"))
        diagnostics = [str(item) for item in raw.get("feedback_block_reasons", []) if str(item).strip()]
        if blocked and not diagnostics:
            diagnostics = ["feedback_blocked"]
        if blocked:
            blocked_reasons.extend(f"{fallback_id}:{item}" for item in diagnostics)

        executor_status = str(raw.get("executor_status", ""))
        if raw.get("placeholder") and not executor_status:
            executor_status = "placeholder_no_qlib"
            diagnostics.append("placeholder_no_qlib")
        if blocked:
            run_status = "blocked"
        elif executor_status in {"qlib_error", "placeholder_no_qlib"}:
            run_status = "failed"
        else:
            run_status = "completed"

        numeric_metrics = {
            key: value
            for key, value in raw.items()
            if not isinstance(value, bool)
            and isinstance(value, Real)
            and math.isfinite(float(value))
        }
        runs.append(
            {
                "run_id": str(raw.get("run_id") or fallback_id),
                "model_id": str(
                    raw.get("experiment")
                    or model_ids_by_role.get(fallback_id)
                    or fallback_id
                ),
                "status": run_status,
                "metrics": numeric_metrics,
                "diagnostics": diagnostics,
            }
        )

    if blocked_reasons:
        status = "inconclusive"
        verdict = "inconclusive"
        summary = "Experiment execution completed with blocked evidence diagnostics."
    elif not runs or any(run["status"] == "failed" for run in runs):
        status = "failed"
        verdict = "inconclusive"
        summary = "Experiment execution failed or produced no usable runs."
    else:
        status = "completed"
        verdict = {"positive_increment": "supporting", "negative_increment": "contradictory"}.get(
            feedback_type or "", "neutral"
        )
        summary = "Experiment execution completed; evidence classification remains bounded by the declared evaluation."

    all_limitations = [str(item) for item in limitations if str(item).strip()]
    all_limitations.extend(blocked_reasons)
    result = {
        "schema_version": "system.experiment_result.v1",
        "experiment_id": spec["experiment_id"],
        "status": status,
        "engine": {
            "adapter": spec["engine"]["adapter"],
            "executor": spec["engine"].get("executor", ""),
            "version": engine_version or spec["engine"].get("version", ""),
        },
        "spec_sha256": spec_sha256(spec),
        "dataset": {
            "release": spec["dataset"]["release"],
            "input_artifacts": [dict(item) for item in input_artifacts],
        },
        "runs": runs,
        "evidence": {
            "verdict": verdict,
            "summary": summary,
            "confidence": None,
            "artifact_refs": [],
        },
        "limitations": all_limitations,
        "governance": {
            "evidence_only": True,
            "judgment_authority": False,
            "feedback_usable": status == "completed" and not blocked_reasons,
            "promotion_eligible": False,
        },
    }
    errors = validate_result(result)
    if errors:
        raise ExperimentProtocolError("Generated invalid Experiment Result: " + "; ".join(errors))
    return result


def write_result(path: str | Path, result: Mapping[str, Any]) -> Path:
    """Validate and atomically write a Result Artifact."""
    errors = validate_result(result)
    if errors:
        raise ExperimentProtocolError("Cannot write invalid Experiment Result: " + "; ".join(errors))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return target


def _validate(payload: Mapping[str, Any], schema_path: Path) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["payload must be an object"]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"schema unavailable: {exc}"]
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = []
    for error in sorted(
        validator.iter_errors(dict(payload)),
        key=lambda item: tuple(str(part) for part in item.path),
    ):
        location = ".".join(str(part) for part in error.path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentProtocolError(f"Cannot load experiment spec {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExperimentProtocolError(f"Experiment spec {path} must contain an object")
    return payload


__all__ = [
    "ExperimentProtocolError",
    "build_result_artifact",
    "load_registry",
    "load_spec",
    "spec_sha256",
    "validate_registry",
    "validate_result",
    "validate_spec",
    "write_result",
]
