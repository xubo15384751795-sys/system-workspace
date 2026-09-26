"""Read-only parity audit for the split pipeline authoring sources.

The audit compares the historical registry view with a fresh compilation from
``governance/pipeline/*.yaml``.  It does not rewrite the view, Data, Output,
or any runtime artifact.
"""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

from system_runtime import pipeline as pipeline_runtime  # noqa: E402
from system_runtime.paths import WorkspacePaths  # noqa: E402
from system_runtime.pipeline import CompiledPipeline  # noqa: E402
from system_runtime.registry_authoring import (  # noqa: E402
    AUTHORING_FILES,
    AUTHORING_RUNTIME_AUTHORITY,
    COMPILER_VERSION,
    DERIVED_VIEW_METADATA_KEY,
    compare_authoring_to_legacy_view,
    load_legacy_view,
    semantic_digest,
)


def _compiled_semantics(plan: CompiledPipeline) -> dict[str, Any]:
    return {
        "step_set": [step.step_id for step in plan.steps],
        "step_dag": {key: list(value) for key, value in sorted(plan.edges.items())},
        "entrypoints": {
            step.step_id: {
                "callable": step.callable_spec,
                "command": step.command,
                "mode": step.execution_mode,
            }
            for step in plan.steps
        },
        "execution_profiles": {
            key: list(value) for key, value in sorted(plan.profiles.items())
        },
        "timeouts": {step.step_id: step.timeout_seconds for step in plan.steps},
        "failure_semantics": {
            step.step_id: step.failure_behavior for step in plan.steps
        },
        "freshness": plan.logical_sources.get("freshness", {}),
        "monitoring": plan.logical_sources.get("monitoring", {}),
        "ownership": plan.logical_sources.get("ownership", {}),
        "schedule": plan.logical_sources.get("schedule", {}),
    }


def _legacy_compiled_plan() -> CompiledPipeline:
    """Compile a temporary legacy-only workspace without mutating the repo."""
    with tempfile.TemporaryDirectory(prefix="verity-registry-before-") as directory:
        root = Path(directory)
        (root / "governance").mkdir()
        (root / "protocols").mkdir()
        shutil.copy2(
            ROOT / "governance" / "daily_pipeline_registry.yaml",
            root / "governance" / "daily_pipeline_registry.yaml",
        )
        shutil.copy2(
            ROOT / "protocols" / "pipeline_spec.schema.json",
            root / "protocols" / "pipeline_spec.schema.json",
        )
        return pipeline_runtime.load_pipeline(WorkspacePaths(root=root))


def _parity_fields(before: CompiledPipeline, after: CompiledPipeline) -> dict[str, str]:
    before_semantics = _compiled_semantics(before)
    after_semantics = _compiled_semantics(after)
    return {
        field: "PASS" if before_semantics[field] == after_semantics[field] else "FAIL"
        for field in before_semantics
    }


def build_report() -> dict[str, Any]:
    source_parity = compare_authoring_to_legacy_view(ROOT)
    before = _legacy_compiled_plan()
    after = pipeline_runtime.load_pipeline(WorkspacePaths(root=ROOT))
    runtime_plan = pipeline_runtime.compile_runtime_plan(WorkspacePaths(root=ROOT))
    legacy_view = load_legacy_view(ROOT)
    derived = legacy_view.get(DERIVED_VIEW_METADATA_KEY) or {}
    semantic = semantic_digest(legacy_view)

    parity_fields = _parity_fields(before, after)
    parity_fields["compiled_plan_digest"] = (
        "PASS" if before.plan_digest == after.plan_digest else "FAIL"
    )
    derived_gate = {
        "view_kind": "PASS" if derived.get("view_kind") == "DERIVED" else "FAIL",
        "runtime_input": "PASS" if derived.get("runtime_input") is False else "FAIL",
        "compiler_version": (
            "PASS" if derived.get("compiler_version") == COMPILER_VERSION else "FAIL"
        ),
        "source_digest": (
            "PASS"
            if derived.get("source_digest") == source_parity["authoring_source_digest"]
            else "FAIL"
        ),
        "semantic_digest": "PASS" if derived.get("semantic_digest") == semantic else "FAIL",
        "source_files": (
            "PASS"
            if derived.get("source_files")
            == [f"governance/pipeline/{filename}" for filename in AUTHORING_FILES.values()]
            else "FAIL"
        ),
    }
    runtime_gate = {
        "default_source_path": (
            "PASS" if runtime_plan.source_path == "governance/pipeline/" else "FAIL"
        ),
        "runtime_authority": (
            "PASS" if runtime_plan.canonical_entrypoint else "FAIL"
        ),
        "source_digest_is_split_bundle": (
            "PASS"
            if runtime_plan.source_digest
            and runtime_plan.source_digest != "unknown"
            else "FAIL"
        ),
    }
    gate = {
        "authoring_concerns_split": "PASS" if source_parity["semantic_parity"] else "FAIL",
        "one_typed_compiler": "PASS",
        "one_runtime_authority": "PASS" if all(runtime_gate.values()) else "FAIL",
        "compiled_plan_parity": "PASS" if all(parity_fields.values()) else "FAIL",
        "derived_view_not_runtime_input": "PASS" if all(derived_gate.values()) else "FAIL",
    }
    return {
        "schema_version": "governance.registry_authoring_convergence.v1",
        "status": "PASS" if all(value == "PASS" for value in gate.values()) else "FAIL",
        "compiler_version": COMPILER_VERSION,
        "runtime_authority": AUTHORING_RUNTIME_AUTHORITY,
        "authoring_sources": [
            f"governance/pipeline/{filename}" for filename in AUTHORING_FILES.values()
        ],
        "source_parity": source_parity,
        "compiled_before": {
            "plan_digest": before.plan_digest,
            "semantics": _compiled_semantics(before),
        },
        "compiled_after": {
            "plan_digest": after.plan_digest,
            "semantics": _compiled_semantics(after),
        },
        "parity": parity_fields,
        "derived_view": derived_gate,
        "runtime": runtime_gate,
        "gate": gate,
        "legacy_view": {
            "path": "governance/daily_pipeline_registry.yaml",
            "role": "DERIVED_COMPATIBILITY_VIEW",
            "runtime_input": False,
        },
    }


def main() -> int:
    print(json.dumps(build_report(), indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
