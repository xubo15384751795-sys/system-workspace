"""Publish-gate content-clock suite (GE-shaped payload).

Uses Pandera as the evaluation engine. The checked-in expectation document
``configs/great_expectations/expectations/content_freshness_suite.json``
records the suite contract. The ``great_expectations`` pip package is optional
and currently unavailable on Python >=3.14; when importable, results are
annotated but the Pandera clocks remain authoritative for hard-fail decisions.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestration.quality.pandera_checks import evaluate_all_content_clocks


def _ge_available() -> bool:
    """True only for the real pip package (not a local docs directory)."""
    try:
        import great_expectations as ge
    except ImportError:
        return False
    # Repo used to keep suites under ./great_expectations/, which shadowed imports.
    module_file = getattr(ge, "__file__", None) or ""
    if not module_file:
        return False
    return "site-packages" in Path(module_file).parts or "dist-packages" in Path(module_file).parts


def run_content_freshness_suite(*, root: Path | None = None) -> dict[str, Any]:
    """Run Pandera-backed clocks and wrap results as a GE-compatible summary."""
    root = root or Path(__file__).resolve().parents[4]
    results = evaluate_all_content_clocks(root=root)
    success = all(row.get("status") == "fresh" for row in results if row.get("decision_critical"))
    # Non-critical missing clocks warn but do not fail the suite hard-fail set.
    critical_failures = [
        row for row in results if row.get("decision_critical") and row.get("status") != "fresh"
    ]
    suite_doc = root / "configs" / "great_expectations" / "expectations" / "content_freshness_suite.json"
    return {
        "engine": "great_expectations+pandera" if _ge_available() else "pandera",
        "suite": "content_freshness_v1",
        "suite_document": str(suite_doc) if suite_doc.exists() else None,
        "ge_package_available": _ge_available(),
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
