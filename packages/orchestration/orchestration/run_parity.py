"""Read-only parity comparison for two isolated daily run bundles.

The comparator is intentionally downstream of execution.  It does not launch
either runner and never writes a publication surface.  A pair is green only
when step semantics, canonical lineage, input/release identity, and the
generation/current surfaces all agree.  Missing evidence is ``INCOMPLETE``;
it is never treated as an empty success.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from orchestration.shadow_parity import compare_sequence_results
from system_runtime.publish_transaction import GENERATION_SURFACES

SCHEMA_VERSION = "system.orchestration_full_plan_dual_run_parity.v1"
PROMOTION_ALLOWED = False

_EPHEMERAL_JSON_FIELDS = frozenset(
    {
        "generated_at",
        "timestamp",
        "run_id",
        "bundle_run_id",
        "generation_id",
        "started_at",
        "finished_at",
        "duration_s",
        "mtime",
    }
)
_IDENTITY_KEYS = frozenset(
    {
        "release_id",
        "source_release_id",
        "vintage_date",
        "source_vintage_at",
        "available_at",
    }
)
_PUBLICATION_KEYS = frozenset(
    {
        "status",
        "authority",
        "authority_mode",
        "admission_verdict",
        "publish_status",
        "execution_status",
        "spec_status",
    }
)


def _load_json(path: Path) -> tuple[Any | None, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"invalid_json:{type(exc).__name__}"


def _load_jsonl(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.is_file():
        return [], ["missing"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"read_error:{type(exc).__name__}"]
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors.append(f"line_{index}:invalid_json")
            continue
        if not isinstance(value, dict):
            errors.append(f"line_{index}:not_object")
            continue
        rows.append(value)
    return rows, errors


def _canonicalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _EPHEMERAL_JSON_FIELDS
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    return value


def _digest_value(value: Any) -> str:
    encoded = json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _surface_digest_map(generation: Path) -> tuple[dict[str, str], list[str]]:
    """Digest generation surfaces while ignoring only declared JSON ephemera."""
    if not generation.is_dir():
        return {}, ["generation_missing"]
    if not (generation / "current").is_dir():
        return {}, ["current_surface_missing"]
    files: dict[str, str] = {}
    errors: list[str] = []
    for surface in GENERATION_SURFACES:
        root = generation / surface
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = str(path.relative_to(generation))
            if path.name == "latest_run_id.txt":
                continue
            if path.suffix.lower() == ".json":
                payload, error = _load_json(path)
                if error:
                    errors.append(f"{relative}:{error}")
                    files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                else:
                    files[relative] = _digest_value(payload)
            else:
                try:
                    files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
                except OSError as exc:
                    errors.append(f"{relative}:read_error:{type(exc).__name__}")
    return files, errors


def _compare_digest_maps(
    left: Mapping[str, str],
    right: Mapping[str, str],
) -> dict[str, Any]:
    left_keys = set(left)
    right_keys = set(right)
    missing_left = sorted(right_keys - left_keys)
    missing_right = sorted(left_keys - right_keys)
    mismatched = sorted(key for key in left_keys & right_keys if left[key] != right[key])
    status = "MATCH" if not missing_left and not missing_right and not mismatched else "MISMATCH"
    return {
        "status": status,
        "left_file_count": len(left),
        "right_file_count": len(right),
        "missing_left": missing_left,
        "missing_right": missing_right,
        "mismatched": mismatched,
    }


def _identity_values(value: Any) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {key: set() for key in _IDENTITY_KEYS}

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                key_text = str(key)
                if key_text in _IDENTITY_KEYS and isinstance(child, (str, int, float)):
                    text = str(child).strip()
                    if text:
                        found[key_text].add(text)
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return found


def _merge_identity(*values: Any) -> dict[str, set[str]]:
    merged: dict[str, set[str]] = {key: set() for key in _IDENTITY_KEYS}
    for value in values:
        for key, items in _identity_values(value).items():
            merged[key].update(items)
    return merged


def _compare_identity(
    left_manifest: Any,
    right_manifest: Any,
    left_outcome: Any,
    right_outcome: Any,
    left_admission: Any,
    right_admission: Any,
    left_generation: Any,
    right_generation: Any,
) -> dict[str, Any]:
    left = _merge_identity(left_manifest, left_outcome, left_admission, left_generation)
    right = _merge_identity(right_manifest, right_outcome, right_admission, right_generation)
    left_plan = _extract_plan_digest(left_manifest, left_generation)
    right_plan = _extract_plan_digest(right_manifest, right_generation)
    release_left = sorted(left["release_id"] | left["source_release_id"])
    release_right = sorted(right["release_id"] | right["source_release_id"])
    vintage_left = sorted(left["vintage_date"] | left["source_vintage_at"] | left["available_at"])
    vintage_right = sorted(right["vintage_date"] | right["source_vintage_at"] | right["available_at"])
    if (
        not left_plan
        or not right_plan
        or not release_left
        or not release_right
        or not vintage_left
        or not vintage_right
    ):
        status = "INCOMPLETE"
    elif left_plan != right_plan or release_left != release_right or vintage_left != vintage_right:
        status = "MISMATCH"
    else:
        status = "MATCH"
    return {
        "status": status,
        "plan_digest": {"left": left_plan, "right": right_plan},
        "release_ids": {"left": release_left, "right": release_right},
        "vintage_clocks": {"left": vintage_left, "right": vintage_right},
    }


def _extract_plan_digest(manifest: Any, generation: Any) -> str | None:
    for value in (manifest, generation):
        if not isinstance(value, Mapping):
            continue
        direct = value.get("plan_digest")
        if isinstance(direct, str) and direct:
            return direct
        contracts = value.get("contract_digests")
        if isinstance(contracts, Mapping):
            candidate = contracts.get("plan_digest")
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def _publication_state(*values: Any) -> dict[str, str]:
    state: dict[str, str] = {}
    for value in values:
        if not isinstance(value, Mapping):
            continue
        for key in _PUBLICATION_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, (str, int, float)) and str(candidate).strip():
                state[key] = str(candidate)
    return state


def _compare_publication_state(left: Mapping[str, str], right: Mapping[str, str]) -> dict[str, Any]:
    if not left or not right:
        return {"status": "INCOMPLETE", "left": dict(left), "right": dict(right)}
    return {
        "status": "MATCH" if dict(left) == dict(right) else "MISMATCH",
        "left": dict(left),
        "right": dict(right),
    }


def _refresh_generation_metadata(side: dict[str, Any]) -> None:
    generation = side["generation"]
    side["generation_manifest"], side["generation_manifest_error"] = _load_json(
        generation / "manifest.json"
    )
    side["admission"], side["admission_error"] = _load_json(generation / "admission.json")
    side["lineage"], side["lineage_error"] = _load_json(generation / "lineage.json")


def _load_side(run_dir: Path) -> dict[str, Any]:
    manifest, manifest_error = _load_json(run_dir / "manifest.json")
    outcome, outcome_error = _load_json(run_dir / "run_outcome.json")
    steps, step_errors = _load_jsonl(run_dir / "steps.jsonl")
    generation = run_dir / "publish_candidate"
    if not generation.is_dir():
        generation = run_dir / "generation"
    input_snapshot, input_error = _load_json(run_dir / "input_snapshot.json")
    surface_files, surface_errors = _surface_digest_map(generation)
    side = {
        "run_dir": str(run_dir),
        "manifest": manifest,
        "manifest_error": manifest_error,
        "outcome": outcome,
        "outcome_error": outcome_error,
        "steps": steps,
        "step_errors": step_errors,
        "generation": generation,
        "generation_manifest": None,
        "generation_manifest_error": None,
        "admission": None,
        "admission_error": None,
        "lineage": None,
        "lineage_error": None,
        "input_snapshot": input_snapshot,
        "input_error": input_error,
        "surface_files": surface_files,
        "surface_errors": surface_errors,
    }
    _refresh_generation_metadata(side)
    return side


def _side_complete(side: Mapping[str, Any]) -> bool:
    return not any(
        side.get(key)
        for key in (
            "manifest_error",
            "outcome_error",
            "step_errors",
            "generation_manifest_error",
            "admission_error",
            "lineage_error",
            "input_error",
            "surface_errors",
        )
    )


def _required_errors(side: Mapping[str, Any]) -> dict[str, Any]:
    errors: dict[str, Any] = {}
    for key in (
        "manifest_error",
        "outcome_error",
        "step_errors",
        "generation_manifest_error",
        "admission_error",
        "lineage_error",
        "input_error",
        "surface_errors",
    ):
        value = side.get(key)
        if value:
            errors[key] = value
    return errors


def compare_daily_run_bundles(
    legacy_run: Path,
    native_run: Path,
    *,
    legacy_generation: Path | None = None,
    native_generation: Path | None = None,
) -> dict[str, Any]:
    """Compare two already-executed, isolated daily run bundles."""
    left_run = legacy_run.expanduser().resolve()
    right_run = native_run.expanduser().resolve()
    if left_run == right_run:
        return {
            "schema_version": SCHEMA_VERSION,
            "authority": "shadow_only",
            "promotion_allowed": PROMOTION_ALLOWED,
            "status": "INCOMPLETE",
            "reason": "legacy_and_native_run_must_be_distinct",
        }

    left = _load_side(left_run)
    right = _load_side(right_run)
    if legacy_generation is not None:
        left["generation"] = legacy_generation.expanduser().resolve()
        _refresh_generation_metadata(left)
        left["surface_files"], left["surface_errors"] = _surface_digest_map(left["generation"])
    if native_generation is not None:
        right["generation"] = native_generation.expanduser().resolve()
        _refresh_generation_metadata(right)
        right["surface_files"], right["surface_errors"] = _surface_digest_map(right["generation"])

    step_report = compare_sequence_results(
        left["steps"],
        right["steps"],
        plan_digest=_extract_plan_digest(left["manifest"], left["generation_manifest"]),
    ).to_dict()
    input_report = _compare_digest_maps(
        {"input_snapshot": _digest_value(left["input_snapshot"])}
        if left["input_snapshot"] is not None
        else {},
        {"input_snapshot": _digest_value(right["input_snapshot"])}
        if right["input_snapshot"] is not None
        else {},
    )
    identity_report = _compare_identity(
        left["manifest"],
        right["manifest"],
        left["outcome"],
        right["outcome"],
        left["admission"],
        right["admission"],
        left["generation_manifest"],
        right["generation_manifest"],
    )
    publication_report = _compare_publication_state(
        _publication_state(left["manifest"], left["outcome"], left["generation_manifest"]),
        _publication_state(right["manifest"], right["outcome"], right["generation_manifest"]),
    )
    generation_report = _compare_digest_maps(left["surface_files"], right["surface_files"])

    required_errors = {"legacy": _required_errors(left), "native": _required_errors(right)}
    incomplete = bool(required_errors["legacy"] or required_errors["native"])
    dimensions = {
        "inputs": input_report["status"],
        "identity": identity_report["status"],
        "steps": "MATCH"
        if step_report.get("execution_parity") == "MATCH"
        else "MISMATCH",
        "canonical_lineage": step_report.get("canonical_lineage_parity", "NOT_PRESENT"),
        "publication": publication_report["status"],
        "generation_surfaces": generation_report["status"],
    }
    if incomplete or dimensions["canonical_lineage"] == "NOT_PRESENT":
        status = "INCOMPLETE"
    elif any(value == "MISMATCH" for value in dimensions.values()):
        status = "MISMATCH"
    elif all(value == "MATCH" for value in dimensions.values()):
        status = "MATCH"
    else:
        status = "INCOMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "authority": "shadow_only",
        "promotion_allowed": PROMOTION_ALLOWED,
        "status": status,
        "legacy_run": str(left_run),
        "native_run": str(right_run),
        "legacy_generation": str(left["generation"]),
        "native_generation": str(right["generation"]),
        "dimensions": dimensions,
        "required_evidence_errors": required_errors,
        "input_parity": input_report,
        "identity_parity": identity_report,
        "publication_parity": publication_report,
        "step_parity": step_report,
        "generation_surface_parity": generation_report,
    }


__all__ = ["SCHEMA_VERSION", "compare_daily_run_bundles"]
