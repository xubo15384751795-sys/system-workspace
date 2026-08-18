"""Canonical content-clock quality suite.

Pandera owns schema/shape checks and this module owns content-clock evaluation.
Great Expectations is intentionally not claimed or invoked here; it remains a
future optional integration rather than a label attached to Pandera output.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from orchestration.quality.content_freshness import evaluate_all_content_clocks
from orchestration.quality.contracts import QualityResult


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
    """Backward-compatible name for :func:`run_content_freshness_quality_suite`."""
    return run_content_freshness_quality_suite(root=root)


def run_content_freshness_quality_suite(*, root: Path | None = None) -> dict[str, Any]:
    """Run the canonical Pandera-backed content clocks."""
    root = root or Path(__file__).resolve().parents[4]
    results = evaluate_all_content_clocks(root=root)
    success = all(row.get("status") == "fresh" for row in results if row.get("decision_critical"))
    # Non-critical missing clocks warn but do not fail the suite hard-fail set.
    critical_failures = [
        row for row in results if row.get("decision_critical") and row.get("status") != "fresh"
    ]
    suite_doc = root / "configs" / "great_expectations" / "expectations" / "content_freshness_suite.json"
    payload: QualityResult = {
        "schema_version": "quality_result.v1",
        "engine": "pandera",
        "evaluator": "orchestration.quality.content_freshness",
        "suite": "content_freshness_v1",
        "suite_document": str(suite_doc) if suite_doc.exists() else None,
        "great_expectations_ignored": True,
        "status": "PASS" if success else "FAIL",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "success": success,
        "critical_failures": critical_failures,
        "results": results,
        "calendar_engine": "exchange_calendars",
    }
    return cast(dict[str, Any], payload)


def write_ge_validation_artifact(payload: dict[str, Any], *, root: Path | None = None) -> Path:
    """Backward-compatible name for the canonical quality artifact writer."""
    return write_quality_validation_artifact(payload, root=root)


def write_quality_validation_artifact(payload: dict[str, Any], *, root: Path | None = None) -> Path:
    import json

    root = root or Path(__file__).resolve().parents[4]
    out_dir = root / "Output" / "quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "quality_content_freshness.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
