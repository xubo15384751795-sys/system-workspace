#!/usr/bin/env python3
"""Build module activity distribution — which modules are active this cycle.

Reads from daily_pipeline_registry.yaml and checks which steps produced artifacts.
Outputs: Output/system_learning/latest/module_activity_distribution.md

Usage:
    python3 scripts/build_module_activity_distribution.py
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "governance" / "daily_pipeline_registry.yaml"
OUTPUT_PATH = ROOT / "Output" / "system_learning" / "latest" / "module_activity_distribution.md"


def load_registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def check_artifact_exists(path_str: str) -> bool:
    """Check if an artifact path exists."""
    path = ROOT / path_str
    return path.exists()


def build_distribution(reg: dict) -> list[dict[str, Any]]:
    """Build activity distribution for each module."""
    modules: dict[str, dict[str, Any]] = {}

    for step_name, step in reg.get("steps", {}).items():
        if not isinstance(step, dict):
            continue

        owner = step.get("authority", {}).get("owner", step.get("owner", "Unknown"))
        if owner not in modules:
            modules[owner] = {
                "module": owner,
                "steps": [],
                "produced_artifacts": 0,
                "missing_artifacts": 0,
                "affects_core_judgment": False,
            }

        mod = modules[owner]
        mod["steps"].append(step_name)

        # Check if outputs exist
        outputs = step.get("contracts", {}).get("outputs", [])
        for output in outputs:
            if check_artifact_exists(str(output)):
                mod["produced_artifacts"] += 1
            else:
                mod["missing_artifacts"] += 1

        if step.get("authority", {}).get("affects_core_judgment"):
            mod["affects_core_judgment"] = True

    return sorted(modules.values(), key=lambda m: m["module"])


def render_markdown(distribution: list[dict[str, Any]]) -> str:
    """Render distribution as markdown."""
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Module Activity Distribution",
        "",
        f"**Generated:** {now}",
        "",
        "| Module | Steps | Artifacts | Missing | Core Judgment |",
        "|--------|-------|-----------|---------|---------------|",
    ]

    for mod in distribution:
        cj = "✅" if mod["affects_core_judgment"] else "—"
        lines.append(
            f"| {mod['module']} "
            f"| {len(mod['steps'])} "
            f"| {mod['produced_artifacts']} "
            f"| {mod['missing_artifacts']} "
            f"| {cj} |"
        )

    lines += [
        "",
        "## Steps by Module",
        "",
    ]

    for mod in distribution:
        lines.append(f"### {mod['module']}")
        for step in mod["steps"]:
            lines.append(f"- {step}")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    reg = load_registry()
    distribution = build_distribution(reg)
    md = render_markdown(distribution)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(md, encoding="utf-8")
    print(f"Wrote: {OUTPUT_PATH}")

    # Also output JSON
    json_path = OUTPUT_PATH.with_suffix(".json")
    json_path.write_text(json.dumps(distribution, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote: {json_path}")


if __name__ == "__main__":
    main()
