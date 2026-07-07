"""Chart specification layer: separates *what to plot* from the Plotly renderer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChartSpec:
    chart_type: str  # "timeline" | "criticality_bar" | "mismatch_matrix" | "trajectory"
    title: str
    data: dict[str, object]
    config: dict[str, object]
