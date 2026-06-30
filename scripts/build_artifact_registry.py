#!/usr/bin/env python3
"""Build artifact_registry.json for Output/current authority artifacts.

Maps each allowed current artifact to its producer step, path, and TTL
using governance/output_routing_policy.yaml and daily_pipeline_registry.yaml.

Usage:
    python3 scripts/build_artifact_registry.py
    python3 scripts/build_artifact_registry.py --json

Output:
    Output/current/artifact_registry.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from _runtime_io import ROOT, ensure_dir, utc_now, write_json

ROUTING_POLICY_PATH = ROOT / "governance" / "output_routing_policy.yaml"
PIPELINE_REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
OUTPUT_PATH = ROOT / "Output" / "current" / "artifact_registry.json"

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


def build_artifact_registry() -> dict[str, Any]:
    routing = _load_yaml(ROUTING_POLICY_PATH)
    pipeline = _load_yaml(PIPELINE_REGISTRY_PATH)
    producers = _producer_map(pipeline)

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
                "exists": (ROOT / rel_path).exists(),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Output/current artifact registry.")
    parser.add_argument("--json", action="store_true", help="Print registry to stdout.")
    args = parser.parse_args()

    registry = build_artifact_registry()
    ensure_dir(OUTPUT_PATH.parent)
    write_json(OUTPUT_PATH, registry)

    if args.json:
        print(json.dumps(registry, indent=2, ensure_ascii=False))
    else:
        missing = [a["name"] for a in registry["artifacts"] if not a["exists"]]
        print(f"Artifact registry: {OUTPUT_PATH.relative_to(ROOT)}")
        print(f"  Registered: {registry['artifact_count']}")
        if missing:
            print(f"  Missing on disk: {', '.join(missing)}")
        else:
            print("  All registered artifacts present.")


if __name__ == "__main__":
    main()
