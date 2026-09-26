#!/usr/bin/env python3
"""Build artifact_registry.json for Output/current authority artifacts.

Maps each allowed current artifact to its producer step, path, and TTL
using governance/output_routing_policy.yaml and daily_pipeline_registry.yaml.

Usage:
    python3 scripts/commands/weekly/build_artifact_registry.py
    python3 scripts/commands/weekly/build_artifact_registry.py --json

Output:
    Output/current/artifact_registry.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from verity.runtime.runtime_io import ROOT, current_dir, ensure_dir, utc_now, write_json
from system_runtime.registry_authoring import has_authoring_bundle, load_authoring_document

ROUTING_POLICY_PATH = ROOT / "governance" / "output_routing_policy.yaml"
PIPELINE_REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
OUTPUT_PATH = current_dir() / "artifact_registry.json"

# Artifacts produced outside the daily pipeline (manual / refresh chain).
MANUAL_PRODUCERS: dict[str, dict[str, Any]] = {
    "artifact_registry.json": {
        "producer_step": "build_artifact_registry",
        "ttl_hours": 24,
        "classification": "current",
    },
    "artifact_navigator.md": {
        "producer_step": "build_artifact_navigator",
        "ttl_hours": 24,
        "classification": "current",
    },
    "artifact_navigator.json": {
        "producer_step": "build_artifact_navigator",
        "ttl_hours": 24,
        "classification": "current",
    },
}


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _producer_map(pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map Output/current/<filename> -> producer metadata."""
    mapping: dict[str, dict[str, Any]] = {}
    steps = pipeline.get("steps") or {}
    for step_id, step in steps.items():
        if not isinstance(step, dict):
            continue
        artifact_path = str(step.get("artifact_path", "")).strip()
        if not artifact_path.startswith("Output/current/"):
            for produced in step.get("produces") or []:
                produced_path = str(produced).strip()
                if produced_path.startswith("Output/current/") and produced_path.count("/") >= 2:
                    artifact_path = produced_path
                    break
        if not artifact_path.startswith("Output/current/"):
            continue
        filename = Path(artifact_path).name
        mapping[filename] = {
            "producer_step": step_id,
            "ttl_hours": step.get("ttl_hours", pipeline.get("_defaults", {}).get("ttl_hours", 48)),
            "classification": "current",
            "owner": step.get("owner", "unknown"),
        }
    return mapping


def build_artifact_registry(
    *,
    root: Path | None = None,
    routing_policy_path: Path | None = None,
    pipeline_registry_path: Path | None = None,
    current_path: Path | None = None,
) -> dict[str, Any]:
    """Build the registry against an explicit current output surface.

    The optional paths are used by the bounded native asset adapter.  The
    no-argument form keeps the existing runner and test contract, including
    module-level path overrides.
    """
    workspace_root = root or ROOT
    routing_path = routing_policy_path or (
        workspace_root / "governance" / "output_routing_policy.yaml"
        if root is not None
        else ROUTING_POLICY_PATH
    )
    routing = _load_yaml(routing_path)
    if pipeline_registry_path is not None:
        pipeline = _load_yaml(pipeline_registry_path)
    elif has_authoring_bundle(workspace_root):
        pipeline = load_authoring_document(workspace_root)
    else:
        # Compatibility for an installed checkout predating the split
        # authoring bundle.  The repository default takes the compiler path.
        pipeline_path = (
            workspace_root / "governance" / "daily_pipeline_registry.yaml"
            if root is not None
            else PIPELINE_REGISTRY_PATH
        )
        pipeline = _load_yaml(pipeline_path)
    producers = _producer_map(pipeline)
    # Resolve the default through the generation-aware runtime helper.  With
    # no generation active this is the same legacy Output/current path; during
    # an isolated generation run it prevents existence checks from leaking
    # back to the published compatibility surface.
    if current_path is not None:
        current = current_path
    elif root is None:
        current = current_dir()
    else:
        current = workspace_root / "Output" / "current"

    allowed = (
        routing.get("groups", {})
        .get("current", {})
        .get("allowed_artifacts", [])
    )

    artifacts: list[dict[str, Any]] = []
    for name in allowed:
        rel_path = f"Output/current/{name}"
        meta = producers.get(name) or MANUAL_PRODUCERS.get(name, {})
        artifacts.append(
            {
                "name": name,
                "path": rel_path,
                "display_group": "current",
                "producer_step": meta.get("producer_step", "unknown"),
                "owner": meta.get("owner", "Workbench"),
                "ttl_hours": meta.get("ttl_hours", 24),
                "classification": meta.get("classification", "current"),
                "exists": (current / name).exists(),
            }
        )

    return {
        "schema_version": "artifact_registry.v1",
        "generated_at": utc_now().isoformat(),
        "display_group": "current",
        "source_policy": "governance/output_routing_policy.yaml",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }


def write_artifact_registry(
    registry: dict[str, Any],
    *,
    output_path: Path | None = None,
) -> Path:
    """Write an artifact registry to an explicit output surface."""
    target = output_path or OUTPUT_PATH
    ensure_dir(target.parent)
    write_json(target, registry)
    return target


def _display_path(path: Path) -> str:
    """Render an output path without assuming it lives under the workspace."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Output/current artifact registry.")
    parser.add_argument("--json", action="store_true", help="Print registry to stdout.")
    args = parser.parse_args()

    registry = build_artifact_registry()
    output_path = write_artifact_registry(registry)

    if args.json:
        print(json.dumps(registry, indent=2, ensure_ascii=False))
    else:
        missing = [a["name"] for a in registry["artifacts"] if not a["exists"]]
        print(f"Artifact registry: {_display_path(output_path)}")
        print(f"  Registered: {registry['artifact_count']}")
        if missing:
            print(f"  Missing on disk: {', '.join(missing)}")
        else:
            print("  All registered artifacts present.")


if __name__ == "__main__":
    main()
