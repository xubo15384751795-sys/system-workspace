"""Generate benchmark reports: comparison report (markdown) and benchmark events.

Writes feedback/comparison_report.md and events/benchmark_event.json.
The event is the ONLY artifact the Learning Hub may consume.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import cast

BENCHMARKS_ROOT = cast(Path, _workspace_root() / "Output" / "state" / "benchmarks" / "market_feedback")


def write_comparison_report(benchmark_id: str) -> Path:
    """Generate a human-readable comparison report from feedback data."""
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    feedback_dir = benchmark_dir / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    summary_path = feedback_dir / "metrics_summary.json"
    decision_path = feedback_dir / "feedback_decision.json"

    summary = {}
    decision = {}

    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if decision_path.exists():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))

    lines = [
        "# Market Feedback Benchmark Report",
        "",
        f"**Benchmark ID:** `{benchmark_id}`",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Feedback Classification",
        "",
        f"**Type:** `{decision.get('feedback_type', 'unknown')}`",
        "",
        f"**Summary:** {decision.get('summary', 'N/A')}",
        "",
    ]

    # Metric deltas table
    deltas = summary.get("metric_deltas", decision.get("metric_deltas", {}))
    if deltas:
        lines.append("## Metric Deltas (Treatment - Baseline)")
        lines.append("")
        lines.append("| Metric | Delta |")
        lines.append("|--------|-------|")
        for k, v in deltas.items():
            lines.append(f"| {k} | {v:+.6f} |")
        lines.append("")

    # Baseline vs Treatment
    baseline = summary.get("baseline_metrics", {})
    treatment = summary.get("treatment_metrics", {})
    if baseline and treatment:
        lines.append("## Detailed Comparison")
        lines.append("")
        lines.append("| Metric | Baseline | Treatment | Delta |")
        lines.append("|--------|----------|-----------|-------|")
        for k in baseline:
            b = baseline[k]
            t = treatment.get(k)
            if t is not None:
                d = round(t - b, 6)
                lines.append(f"| {k} | {b:.6f} | {t:.6f} | {d:+.6f} |")
        lines.append("")

    # Recommended actions
    actions = decision.get("recommended_action", [])
    if actions:
        lines.append("## Recommended Actions")
        lines.append("")
        for a in actions:
            lines.append(f"- {a}")
        lines.append("")

    report_path = feedback_dir / "comparison_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    return report_path


def build_benchmark_event(benchmark_id: str) -> dict:
    """Construct a Learning Hub event from the benchmark's feedback decision.

    This event is the ONLY artifact from this benchmark that may enter the
    Learning Hub. It must not contain raw Qlib payloads (predictions,
    positions, cache references, raw model artifacts).
    """
    benchmark_dir = BENCHMARKS_ROOT / benchmark_id
    feedback_dir = benchmark_dir / "feedback"
    decision_path = feedback_dir / "feedback_decision.json"
    summary_path = feedback_dir / "metrics_summary.json"

    decision = {}
    summary = {}

    if decision_path.exists():
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    event = {
        "event_type": "market_feedback_benchmark_completed",
        "severity": "info",
        "benchmark_id": benchmark_id,
        "executor": "qlib",
        "feedback_type": decision.get("feedback_type", "inconclusive"),
        "summary": decision.get("summary", ""),
        "metric_deltas": decision.get("metric_deltas", summary.get("metric_deltas", {})),
        "recommended_action": decision.get("recommended_action", []),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Exclude raw Qlib payload
    FORBIDDEN_KEYS = {"predictions", "raw_positions", "qlib_cache", "raw_model"}
    for key in FORBIDDEN_KEYS:
        event.pop(key, None)

    # Write event
    events_dir = benchmark_dir / "events"
    events_dir.mkdir(parents=True, exist_ok=True)
    event_path = events_dir / "benchmark_event.json"
    event_path.write_text(json.dumps(event, indent=2, ensure_ascii=False), encoding="utf-8")

    return event
