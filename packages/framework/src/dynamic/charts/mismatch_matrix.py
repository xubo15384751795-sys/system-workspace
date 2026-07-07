"""MismatchMap → heatmap ChartSpec."""

from __future__ import annotations

import math

import plotly.graph_objects as go

from src.dynamic.charts.chart_spec import ChartSpec
from src.dynamic.mismatch import MismatchMap

_STATUS_CODE = {"normal": 0.0, "watch": 0.25, "warning": 0.55, "critical": 0.9, "unknown": 0.1}


def build_spec(mm: MismatchMap) -> ChartSpec:
    rows: list[dict[str, object]] = []
    for p in mm.profiles:
        rows.append(
            {
                "mismatch_type": p.mismatch_type,
                "pair": f"{p.pair[0]}-{p.pair[1]}",
                "status": p.status,
                "magnitude": p.magnitude,
                "persistence": p.persistence,
            }
        )
    return ChartSpec(
        chart_type="mismatch_matrix",
        title=f"Mismatch heatmap — {mm.case_id or 'case'}",
        data={"rows": rows},
        config={"height": 320},
    )


def render_plotly(spec: ChartSpec) -> go.Figure:
    if spec.chart_type != "mismatch_matrix":
        raise ValueError(
            f"mismatch_matrix renderer expected chart_type 'mismatch_matrix', got {spec.chart_type!r}"
        )
    rows = spec.data.get("rows")
    if not isinstance(rows, list) or not rows:
        fig = go.Figure()
        fig.update_layout(title=spec.title, annotations=[dict(text="No mismatch profiles", showarrow=False)])
        return fig

    y_labels = [str(r.get("mismatch_type", "")) for r in rows if isinstance(r, dict)]
    x_labels = ["status_signal", "magnitude", "persistence"]

    z: list[list[float]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        st = _STATUS_CODE.get(str(r.get("status", "unknown")), 0.1)
        mag = r.get("magnitude")
        per = r.get("persistence")
        mag_v = float(mag) if mag is not None and math.isfinite(float(mag)) else float("nan")
        per_v = float(per) if per is not None and math.isfinite(float(per)) else float("nan")
        z.append([st, mag_v, per_v])

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x_labels,
            y=y_labels,
            colorscale="Blues",
            hoverongaps=False,
        )
    )
    height = int(spec.config.get("height", 320))
    fig.update_layout(
        title=spec.title,
        height=height,
        margin=dict(l=160, r=20, t=60, b=40),
        xaxis=dict(side="bottom"),
        yaxis=dict(autorange="reversed"),
    )
    return fig
