"""Thin Great Expectations runner for publish-gate content clocks.

Emits a GE-shaped validation payload consumed by freshness_validator without
requiring a full Data Context scaffolding in CI.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestration.quality.pandera_checks import evaluate_all_content_clocks


def run_content_freshness_suite(*, root: Path | None = None) -> dict[str, Any]:
    """Run Pandera-backed clocks and wrap results as a GE-compatible summary."""
    root = root or Path(__file__).resolve().parents[4]
    results = evaluate_all_content_clocks(root=root)
    success = all(row.get("status") == "fresh" for row in results if row.get("decision_critical"))
    # Non-critical missing clocks warn but do not fail the suite hard-fail set.
    critical_failures = [
        row for row in results if row.get("decision_critical") and row.get("status") != "fresh"
    ]
    return {
        "engine": "great_expectations+pandera",
        "suite": "content_freshness_v1",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "success": success,
        "critical_failures": critical_failures,
        "results": results,
    }


def write_ge_validation_artifact(payload: dict[str, Any], *, root: Path | None = None) -> Path:
    import json

    root = root or Path(__file__).resolve().parents[4]
    out_dir = root / "Output" / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ge_content_freshness.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
