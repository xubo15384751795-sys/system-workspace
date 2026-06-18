#!/usr/bin/env python3
"""Generate entrypoint registry from scripts/ and pipeline commands.

Hand-maintained fields in governance/entrypoint_registry.yaml are preserved.
Generated overlay adds discovered scripts and pipeline wiring.

Outputs:
    governance/entrypoint_registry.generated.yaml
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
HAND_PATH = ROOT / "governance" / "entrypoint_registry.yaml"
GENERATED_PATH = ROOT / "governance" / "entrypoint_registry.generated.yaml"
PIPELINE_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _discover_scripts(scripts_dir: Path) -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    if not scripts_dir.exists():
        return discovered
    for path in sorted(scripts_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        entry_id = path.stem
        discovered[entry_id] = {
            "script": f"scripts/{path.name}",
            "status": "discovered",
            "owner": "System",
            "description": "Auto-discovered root script",
            "allowed_use": ["discovered_entrypoint"],
            "source": "script_scan",
        }
    return discovered


def _pipeline_scripts(pipeline: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for step_id, step in (pipeline.get("steps", {}) or {}).items():
        command = str(step.get("command", ""))
        if "scripts/" not in command:
            continue
        script = command.split("scripts/", 1)[1].split()[0]
        entry_id = Path(script).stem
        mapped[entry_id] = {
            "script": f"scripts/{script}",
            "status": "pipeline_active",
            "owner": str(step.get("owner", "")),
            "description": f"Pipeline step: {step_id}",
            "allowed_use": ["daily_pipeline"],
            "pipeline_step": step_id,
            "source": "daily_pipeline_registry",
        }
    return mapped


def build_generated_registry(root: Path = ROOT) -> dict[str, Any]:
    hand = _load_yaml(HAND_PATH)
    discovered = _discover_scripts(root / "scripts")
    pipeline = _pipeline_scripts(_load_yaml(PIPELINE_PATH))

    merged: dict[str, dict[str, Any]] = {}
    for entry_id, payload in discovered.items():
        merged[entry_id] = payload
    for entry_id, payload in pipeline.items():
        base = merged.get(entry_id, {})
        merged[entry_id] = {**base, **payload}

    hand_only = {k: v for k, v in hand.items() if k not in merged}
    missing_from_hand = sorted(set(merged) - set(hand))

    return {
        "schema_version": "entrypoint_registry.generated.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": [
            "governance/entrypoint_registry.yaml",
            "governance/daily_pipeline_registry.yaml",
            "scripts/*.py",
        ],
        "entries": merged,
        "hand_maintained_only": hand_only,
        "missing_from_hand_registry": missing_from_hand,
        "counts": {
            "discovered_scripts": len(discovered),
            "pipeline_scripts": len(pipeline),
            "merged_entries": len(merged),
            "hand_maintained_only": len(hand_only),
            "missing_from_hand_registry": len(missing_from_hand),
        },
    }


def write_generated_registry(root: Path = ROOT) -> Path:
    payload = build_generated_registry(root)
    GENERATED_PATH.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return GENERATED_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate entrypoint registry overlay.")
    parser.add_argument("--json", action="store_true", help="Print JSON summary to stdout.")
    args = parser.parse_args()

    output = write_generated_registry(ROOT)
    payload = build_generated_registry(ROOT)
    if args.json:
        print(json.dumps(payload.get("counts", {}), indent=2))
    else:
        counts = payload.get("counts", {})
        print(f"Generated: {output.relative_to(ROOT)}")
        print(f"Merged entries: {counts.get('merged_entries')}")
        print(f"Missing from hand registry: {counts.get('missing_from_hand_registry')}")


if __name__ == "__main__":
    main()
