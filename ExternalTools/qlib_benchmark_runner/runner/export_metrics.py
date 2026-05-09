"""Export aggregated metrics from individual experiment outputs."""

from __future__ import annotations

import json
from pathlib import Path


def export_metrics(output_dir: Path, experiment_names: list[str]) -> Path:
    """Aggregate per-experiment metrics into raw_metrics.json."""
    aggregated = {}

    for name in experiment_names:
        metrics_path = output_dir / name / f"{name}_metrics.json"
        if metrics_path.exists():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            aggregated[name] = metrics

    raw_path = output_dir / "raw_metrics.json"
    raw_path.write_text(json.dumps(aggregated, indent=2), encoding="utf-8")
    return raw_path
