"""Load the split pipeline authoring sources into one runtime document.

The six files under ``governance/pipeline`` are authoring inputs.  They are
partitioned by concern, but they are not six independent registries: this
module is the only merger and validation boundary.  Callers receive one
plain document which is then compiled by :mod:`system_runtime.pipeline` into
the single ``CompiledPipeline`` authority.

``governance/daily_pipeline_registry.yaml`` remains as a generated
compatibility view during the migration.  It is compared against the merged
authoring document by the convergence audit and is never read by the default
compiler when the split sources are present.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

COMPILER_VERSION = "registry-authoring-v1"
AUTHORING_RUNTIME_AUTHORITY = "system_runtime.pipeline.CompiledPipeline"
DERIVED_VIEW_METADATA_KEY = "registry_view"
AUTHORING_DIR = Path("governance/pipeline")
AUTHORING_FILES: dict[str, str] = {
    "topology": "topology.yaml",
    "execution_profiles": "execution_profiles.yaml",
    "monitoring": "monitoring.yaml",
    "freshness": "freshness.yaml",
    "ownership": "ownership.yaml",
    "schedule_metadata": "schedule_metadata.yaml",
}

# A field may have one owner only.  This is deliberately explicit so a new
# concern cannot silently become a second runtime authority.
CONCERN_STEP_FIELDS: dict[str, frozenset[str]] = {
    "topology": frozenset(
        {
            "order",
            "depends_on",
            "input",
            "produces",
            "consumes",
            "contracts",
            "artifact_path",
            "skip_flag",
            "description",
            "note",
        }
    ),
    "execution_profiles": frozenset(
        {"command", "execution", "failure_behavior"}
    ),
    "monitoring": frozenset({"requires_harvester_evidence"}),
    "freshness": frozenset({"ttl_hours", "requires_provenance", "artifact_status"}),
    "ownership": frozenset(
        {
            "owner",
            "status",
            "archive_reason",
            "authority",
            "allowed_to_affect_core_judgment",
            "core_judgment_dependency",
            "blocker",
        }
    ),
    "schedule_metadata": frozenset({"schedule"}),
}

CONCERN_METADATA_FIELDS: dict[str, frozenset[str]] = {
    "topology": frozenset(
        {"schema_version", "updated_at", "generated_views", "external_inputs"}
    ),
    "execution_profiles": frozenset({"execution_profiles", "execution_policy"}),
    "monitoring": frozenset({"monitoring_contracts", "monitoring_classification"}),
    "freshness": frozenset({"content_freshness"}),
    "ownership": frozenset(),
    "schedule_metadata": frozenset(),
}

CONCERN_DEFAULT_FIELDS: dict[str, frozenset[str]] = {
    "topology": frozenset(),
    "execution_profiles": frozenset({"failure_behavior", "execution"}),
    "monitoring": frozenset({"frequency_monitoring"}),
    "freshness": frozenset({"ttl_hours"}),
    "ownership": frozenset(
        {"allowed_to_affect_core_judgment", "core_judgment_dependency"}
    ),
    "schedule_metadata": frozenset({"schedule"}),
}


class RegistryAuthoringError(RuntimeError):
    """Raised when split authoring inputs cannot form one safe document."""


def authoring_paths(root: Path) -> dict[str, Path]:
    """Return the six authoring paths for ``root``."""
    directory = root / AUTHORING_DIR
    return {concern: directory / filename for concern, filename in AUTHORING_FILES.items()}


def authoring_bundle_state(root: Path) -> str:
    """Return ``absent``, ``complete`` or ``partial`` for the source bundle."""
    paths = authoring_paths(root)
    present = [path.exists() for path in paths.values()]
    if not any(present):
        return "absent"
    return "complete" if all(present) else "partial"


def has_authoring_bundle(root: Path) -> bool:
    """Whether the complete split source bundle is available."""
    state = authoring_bundle_state(root)
    if state == "partial":
        missing = [str(path.relative_to(root)) for path in authoring_paths(root).values() if not path.exists()]
        raise RegistryAuthoringError(
            "partial pipeline authoring bundle; missing: " + ", ".join(missing)
        )
    return state == "complete"


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise RegistryAuthoringError(f"{label} must be a mapping")
    return dict(value)


def _load_source(concern: str, path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RegistryAuthoringError(f"cannot load {path}: {exc}") from exc
    document = _mapping(raw, str(path))
    if document.get("concern") != concern:
        raise RegistryAuthoringError(
            f"{path}: concern must be {concern!r}, got {document.get('concern')!r}"
        )
    if document.get("source_kind") != "AUTHORING":
        raise RegistryAuthoringError(f"{path}: source_kind must be AUTHORING")
    if document.get("compiler_version") != COMPILER_VERSION:
        raise RegistryAuthoringError(f"{path}: compiler_version mismatch")
    if document.get("runtime_authority") != AUTHORING_RUNTIME_AUTHORITY:
        raise RegistryAuthoringError(f"{path}: runtime_authority must name CompiledPipeline")

    metadata = _mapping(document.get("metadata", {}), f"{path}.metadata")
    unexpected_metadata = set(metadata) - CONCERN_METADATA_FIELDS[concern]
    if unexpected_metadata:
        raise RegistryAuthoringError(
            f"{path}: metadata fields owned by another concern: {sorted(unexpected_metadata)}"
        )
    defaults = _mapping(document.get("defaults", {}), f"{path}.defaults")
    unexpected_defaults = set(defaults) - CONCERN_DEFAULT_FIELDS[concern]
    if unexpected_defaults:
        raise RegistryAuthoringError(
            f"{path}: default fields owned by another concern: {sorted(unexpected_defaults)}"
        )
    steps = _mapping(document.get("steps", {}), f"{path}.steps")
    allowed_fields = CONCERN_STEP_FIELDS[concern]
    for step_id, raw_step in steps.items():
        step = _mapping(raw_step, f"{path}.steps.{step_id}")
        unexpected_step = set(step) - allowed_fields
        if unexpected_step:
            raise RegistryAuthoringError(
                f"{path}.steps.{step_id}: fields owned by another concern: "
                f"{sorted(unexpected_step)}"
            )
    return {
        "metadata": metadata,
        "defaults": defaults,
        "steps": {str(step_id): dict(raw_step) for step_id, raw_step in steps.items()},
    }


def _merge_unique(target: dict[str, Any], values: Mapping[str, Any], label: str) -> None:
    for key, value in values.items():
        if key in target:
            raise RegistryAuthoringError(f"duplicate {label} field: {key}")
        target[key] = copy.deepcopy(value)


def load_authoring_document(root: Path) -> dict[str, Any]:
    """Merge and validate the six authoring sources into one registry document."""
    if not has_authoring_bundle(root):
        raise RegistryAuthoringError(f"pipeline authoring bundle is absent under {root}")
    paths = authoring_paths(root)
    sources = {
        concern: _load_source(concern, paths[concern]) for concern in AUTHORING_FILES
    }

    step_sets = {concern: set(source["steps"]) for concern, source in sources.items()}
    all_step_ids = set().union(*step_sets.values())
    if not all_step_ids:
        raise RegistryAuthoringError("pipeline authoring sources contain no steps")
    if any(step_ids != all_step_ids for step_ids in step_sets.values()):
        missing = {
            concern: sorted(all_step_ids - step_ids)
            for concern, step_ids in step_sets.items()
            if step_ids != all_step_ids
        }
        raise RegistryAuthoringError(f"all authoring sources must cover the same steps: {missing}")

    document: dict[str, Any] = {}
    for concern in AUTHORING_FILES:
        _merge_unique(document, sources[concern]["metadata"], "metadata")
    defaults: dict[str, Any] = {}
    for concern in AUTHORING_FILES:
        _merge_unique(defaults, sources[concern]["defaults"], "default")
    document["_defaults"] = defaults

    steps: dict[str, dict[str, Any]] = {step_id: {} for step_id in sorted(all_step_ids)}
    for concern in AUTHORING_FILES:
        for step_id in sorted(all_step_ids):
            _merge_unique(steps[step_id], sources[concern]["steps"][step_id], f"step {step_id}")
    document["steps"] = steps

    expected = {
        "schema_version",
        "updated_at",
        "generated_views",
        "external_inputs",
        "execution_profiles",
        "execution_policy",
        "_defaults",
        "content_freshness",
        "monitoring_contracts",
        "monitoring_classification",
        "steps",
    }
    missing = sorted(expected - set(document))
    if missing:
        raise RegistryAuthoringError(f"merged authoring document missing fields: {missing}")
    return document


def load_legacy_view(root: Path) -> dict[str, Any]:
    """Load the generated compatibility view for parity checks only."""
    path = root / "governance" / "daily_pipeline_registry.yaml"
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise RegistryAuthoringError(f"cannot load registry compatibility view: {exc}") from exc
    return _mapping(value, str(path))


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    if isinstance(value, tuple):
        return [_canonical(item) for item in value]
    return value


def semantic_digest(document: Mapping[str, Any]) -> str:
    """Hash the normalized registry semantics, independent of YAML layout."""
    semantic_document = dict(document)
    # The legacy YAML is retained as a human/compatibility view.  Its
    # provenance envelope is deliberately not part of runtime semantics.
    semantic_document.pop(DERIVED_VIEW_METADATA_KEY, None)
    payload = _canonical(semantic_document)
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def authoring_source_digest(root: Path) -> str:
    """Hash the six source bytes and compiler version for runtime identity."""
    paths = authoring_paths(root)
    if not has_authoring_bundle(root):
        raise RegistryAuthoringError(f"pipeline authoring bundle is absent under {root}")
    files = {
        str(AUTHORING_DIR / AUTHORING_FILES[concern]): hashlib.sha256(
            paths[concern].read_bytes()
        ).hexdigest()
        for concern in AUTHORING_FILES
    }
    payload = {"compiler_version": COMPILER_VERSION, "files": files}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compare_authoring_to_legacy_view(root: Path) -> dict[str, Any]:
    """Return semantic parity evidence without changing either input."""
    compiled = load_authoring_document(root)
    legacy = load_legacy_view(root)
    compiled_digest = semantic_digest(compiled)
    legacy_digest = semantic_digest(legacy)
    return {
        "compiled_semantic_digest": compiled_digest,
        "legacy_view_semantic_digest": legacy_digest,
        "semantic_parity": compiled_digest == legacy_digest,
        "authoring_source_digest": authoring_source_digest(root),
        "compiler_version": COMPILER_VERSION,
        "runtime_authority": AUTHORING_RUNTIME_AUTHORITY,
    }
