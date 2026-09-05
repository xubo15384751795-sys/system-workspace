"""CriticalityState → horizontal bar ChartSpec (linear bars; no radial gauge)."""

from __future__ import annotations

import plotly.graph_objects as go

from src.dynamic.charts.chart_spec import ChartSpec
from src.dynamic.criticality import CriticalityState

_STATUS_SCORE = {"safe": 0.0, "watch": 0.25, "near_threshold": 0.6, "crossed": 1.0, "unknown": -0.05}


def build_spec(cs: CriticalityState) -> ChartSpec:
    bars: list[dict[str, object]] = []
    if cs.level_risk is not None:
        bars.append({"label": "level_risk", "value": float(cs.level_risk)})
    if cs.transition_risk is not None:
        bars.append({"label": "transition_risk", "value": float(cs.transition_risk)})
    if cs.distance_to_threshold is not None and cs.nearest_threshold:
        # Normalize distance by (distance + small epsilon); display-only diagnostic.
        d = float(cs.distance_to_threshold)
        denom = max(d, 1e-6)
        bars.append({"label": "inv_distance (viz)", "value": float(min(1.0, 1.0 / denom))})
    bars.append({"label": "status_score", "value": float(_STATUS_SCORE.get(cs.status, 0.0))})

    return ChartSpec(
        chart_type="criticality_bar",
        title=f"Criticality bars — {cs.case_id or 'case'}",
        data={"bars": bars, "status": cs.status},
        config={"height": 360},
    )


def render_plotly(spec: ChartSpec) -> go.Figure:
    if spec.chart_type != "criticality_bar":
        raise ValueError(
            f"criticality_bar renderer expected chart_type 'criticality_bar', got {spec.chart_type!r}"
        )
    bars = spec.data.get("bars")
    if not isinstance(bars, list) or not bars:
        fig = go.Figure()
        fig.update_layout(title=spec.title, annotations=[dict(text="No bar metrics available", showarrow=False)])
        return fig

    labels = [str(b.get("label", "")) for b in bars if isinstance(b, dict)]
    values = [float(b.get("value", 0.0)) for b in bars if isinstance(b, dict)]

    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(color="#4C78A8"),
        )
    )
    height = int(spec.config.get("height", 360))
    fig.update_layout(
        title=spec.title,
        height=height,
        margin=dict(l=120, r=20, t=60, b=40),
        xaxis=dict(range=[0, 1.05], title="0–1 diagnostic scale"),
        yaxis=dict(title=""),
    )
    return fig
