from __future__ import annotations

from typing import Sequence

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from src.core.models import Snapshot
from src.operators.operator_schema import OperatorDiagnostics


FAMILY_COLORS = {
    "compression": "#d66a5f",
    "curvature": "#d99a52",
    "shadow_transfer": "#6b83c7",
    "realization": "#c84b6e",
    "intervention": "#7aa879",
    "mechanism": "#9aa6b2",
}
_DEFAULT_COLOR = "#a8b0bd"

_SINGULAR_SHADE = "rgba(214, 106, 95, 0.10)"
_TRACE_COLOR = "rgba(148, 163, 184, 0.55)"
_CURRENT_COLOR = "#e5e7eb"


def _family_color(family: str) -> str:
    return FAMILY_COLORS.get(family, _DEFAULT_COLOR)


def render_phase_space_chart(
    snapshots: Sequence[Snapshot],
    op_diag: OperatorDiagnostics | None = None,
    sigma_threshold: float = 2.0,
) -> None:
    if not snapshots:
        st.caption("No history available for phase space.")
        return

    dates = [s.run_date for s in snapshots]
    M_vals = [s.proxy.M or 0.0 for s in snapshots]
    D_vals = [s.proxy.D or 0.0 for s in snapshots]
    K_vals = [s.proxy.K or 0.0 for s in snapshots]
    X_vals = [s.proxy.X or 0.0 for s in snapshots]

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["M / D  (Mismatch vs Degrees of Freedom)", "K / X  (Curvature vs Shadow Load)"],
        horizontal_spacing=0.10,
    )

    # --- M / D plane ---
    fig.add_trace(
        go.Scatter(
            x=M_vals,
            y=D_vals,
            mode="lines+markers",
            line={"color": _TRACE_COLOR, "width": 1.2},
            marker={"size": 4, "color": _TRACE_COLOR},
            hovertemplate="M=%{x:.3f}<br>D=%{y:.3f}<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    # Current point
    fig.add_trace(
        go.Scatter(
            x=[M_vals[-1]],
            y=[D_vals[-1]],
            mode="markers+text",
            marker={"size": 10, "color": _CURRENT_COLOR, "symbol": "circle"},
            text=[dates[-1]],
            textposition="top right",
            textfont={"size": 10, "color": _CURRENT_COLOR},
            hovertemplate=f"Current<br>M={M_vals[-1]:.3f}<br>D={D_vals[-1]:.3f}<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=1,
    )

    # --- K / X plane ---
    fig.add_trace(
        go.Scatter(
            x=K_vals,
            y=X_vals,
            mode="lines+markers",
            line={"color": _TRACE_COLOR, "width": 1.2},
            marker={"size": 4, "color": _TRACE_COLOR},
            hovertemplate="K=%{x:.3f}<br>X=%{y:.3f}<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Scatter(
            x=[K_vals[-1]],
            y=[X_vals[-1]],
            mode="markers+text",
            marker={"size": 10, "color": _CURRENT_COLOR, "symbol": "circle"},
            text=[dates[-1]],
            textposition="top right",
            textfont={"size": 10, "color": _CURRENT_COLOR},
            hovertemplate=f"Current<br>K={K_vals[-1]:.3f}<br>X={X_vals[-1]:.3f}<extra></extra>",
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    # Operator event markers
    if op_diag is not None:
        app_by_date: dict[str, list] = {}
        for app in op_diag.applications:
            key = app.event_date or ""
            app_by_date.setdefault(key, []).append(app)

        for date_key, apps in app_by_date.items():
            if not date_key:
                continue
            family = apps[0].family
            color = _family_color(family)
            labels = ", ".join(a.operator_name for a in apps[:3])
            # Find the snapshot closest to this event date
            idx = _nearest_date_idx(dates, date_key)
            if idx is None:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[M_vals[idx]],
                    y=[D_vals[idx]],
                    mode="markers",
                    marker={"size": 9, "color": color, "symbol": "diamond", "opacity": 0.85},
                    name=family,
                    hovertemplate=f"{labels}<br>{date_key}<extra></extra>",
                    showlegend=False,
                ),
                row=1,
                col=1,
            )
            fig.add_trace(
                go.Scatter(
                    x=[K_vals[idx]],
                    y=[X_vals[idx]],
                    mode="markers",
                    marker={"size": 9, "color": color, "symbol": "diamond", "opacity": 0.85},
                    name=family,
                    hovertemplate=f"{labels}<br>{date_key}<extra></extra>",
                    showlegend=False,
                ),
                row=1,
                col=2,
            )

    fig.update_layout(
        height=380,
        margin={"t": 40, "b": 24, "l": 38, "r": 24},
        paper_bgcolor="#0e1116",
        plot_bgcolor="#0e1116",
        font={"color": "#d1d5db", "size": 11},
        title=None,
    )
    _style_axis(fig, "xaxis", "M  (Anchor Mismatch)")
    _style_axis(fig, "yaxis", "D  (Degrees of Freedom)")
    _style_axis(fig, "xaxis2", "K  (Curvature)")
    _style_axis(fig, "yaxis2", "X  (Shadow Load)")
    for ann in fig.layout.annotations:
        ann.font.color = "#9aa6b2"
        ann.font.size = 11

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Family legend
    families_seen = set()
    if op_diag:
        families_seen = {app.family for app in op_diag.applications}
    if families_seen:
        chips = "".join(
            f'<span style="display:inline-flex;align-items:center;gap:5px;margin:0 10px 4px 0;font-size:11px;color:#a8b0bd;">'
            f'<span style="width:9px;height:9px;background:{_family_color(f)};border-radius:2px;"></span>{f}</span>'
            for f in sorted(families_seen)
        )
        st.markdown(f'<div style="margin:2px 0 6px 0;">{chips}</div>', unsafe_allow_html=True)


def _style_axis(fig: go.Figure, axis_name: str, title: str) -> None:
    axis = getattr(fig.layout, axis_name, None)
    if axis is None:
        return
    axis.update(
        title_text=title,
        title_font={"size": 10, "color": "#8b95a5"},
        showgrid=True,
        gridcolor="rgba(148,163,184,0.12)",
        zeroline=True,
        zerolinecolor="rgba(148,163,184,0.28)",
        linecolor="rgba(148,163,184,0.20)",
        tickfont={"color": "#9ca3af", "size": 9},
    )


def _nearest_date_idx(dates: list[str], target: str) -> int | None:
    if not dates:
        return None
    try:
        from pandas import to_datetime

        target_ts = to_datetime(target)
        parsed = [to_datetime(d) for d in dates]
        diffs = [abs((ts - target_ts).days) for ts in parsed]
        return diffs.index(min(diffs))
    except Exception:
        return None
