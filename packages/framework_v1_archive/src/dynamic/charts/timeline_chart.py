"""TemporalFrame → ChartSpec → Plotly figure."""

from __future__ import annotations

from datetime import datetime

import plotly.graph_objects as go

from src.dynamic.charts.chart_spec import ChartSpec
from src.dynamic.models import TemporalFrame


def build_spec(frame: TemporalFrame) -> ChartSpec:
    return ChartSpec(
        chart_type="timeline",
        title=f"Event timeline — {frame.case_id}",
        data={
            "phases": [
                {
                    "name": p.name,
                    "start": p.start,
                    "end": p.end,
                    "mechanism": p.dominant_mechanism,
                }
                for p in frame.phases
            ]
        },
        config={"height": 420, "font_size": 12},
    )


def _parse(d: str) -> datetime:
    return datetime.fromisoformat(d)


def render_plotly(spec: ChartSpec) -> go.Figure:
    if spec.chart_type != "timeline":
        raise ValueError(f"timeline_chart renderer expected chart_type 'timeline', got {spec.chart_type!r}")
    phases = spec.data.get("phases")
    if not isinstance(phases, list):
        raise ValueError("timeline ChartSpec.data must include 'phases' list")

    fig = go.Figure()
    y_labels: list[str] = []
    for i, raw in enumerate(phases):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name", f"phase_{i}"))
        start = str(raw["start"])
        end = str(raw["end"])
        y_labels.append(name)
        x0, x1 = _parse(start), _parse(end)
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[name, name],
                mode="lines+markers",
                line=dict(width=6),
                name=name,
                hovertemplate=(
                    f"<b>{name}</b><br>"
                    f"{start} → {end}<br>"
                    f"{raw.get('mechanism') or ''}"
                    "<extra></extra>"
                ),
            )
        )

    height = int(spec.config.get("height", 420))
    font_size = int(spec.config.get("font_size", 12))
    fig.update_layout(
        title=spec.title,
        height=height,
        margin=dict(l=40, r=20, t=60, b=40),
        xaxis_title="Date",
        yaxis=dict(type="category", categoryorder="array", categoryarray=y_labels),
        showlegend=False,
        font=dict(size=font_size),
    )
    return fig
