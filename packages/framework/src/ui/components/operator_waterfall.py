from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from src.operators.operator_schema import OperatorDiagnostics


CHANNEL_COLORS = {
    "M": "#d66a5f",
    "D": "#d99a52",
    "K": "#56a3a6",
    "X": "#6b83c7",
}
FAMILY_COLORS = {
    "compression": "#d66a5f",
    "curvature": "#d99a52",
    "shadow_transfer": "#6b83c7",
    "realization": "#c84b6e",
    "intervention": "#7aa879",
    "mechanism": "#9aa6b2",
}
_POS_COLOR = "#d99a52"
_NEG_COLOR = "#56a3a6"
_DEFAULT_FAMILY_COLOR = "#a8b0bd"


def render_operator_waterfall(op_diag: OperatorDiagnostics) -> None:
    if not op_diag.applications:
        st.caption("No operators applied in current window.")
        return

    apps = op_diag.applications
    short_names = [a.operator_name for a in apps]
    channels = ["M", "D", "K", "X"]

    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=["M — Anchor Mismatch", "D — Degrees of Freedom", "K — Curvature", "X — Shadow Load"],
        vertical_spacing=0.14,
        horizontal_spacing=0.10,
    )
    positions = [(1, 1), (1, 2), (2, 1), (2, 2)]

    for (row, col), channel in zip(positions, channels):
        deltas = [float(a.delta.get(channel, 0.0)) for a in apps]
        colors = [
            (_POS_COLOR if d > 1e-12 else _NEG_COLOR if d < -1e-12 else "rgba(148,163,184,0.3)")
            for d in deltas
        ]
        hover = [
            f"{short_names[i]}<br>Δ{channel}={deltas[i]:+.4f}<br>{apps[i].event_date or '-'}"
            for i in range(len(apps))
        ]
        fig.add_trace(
            go.Bar(
                x=short_names,
                y=deltas,
                marker_color=colors,
                hovertemplate="%{customdata}<extra></extra>",
                customdata=hover,
                showlegend=False,
            ),
            row=row,
            col=col,
        )
        fig.add_hline(y=0, line_width=0.8, line_color="rgba(148,163,184,0.3)", row=row, col=col)

    fig.update_layout(
        height=440,
        margin={"t": 36, "b": 28, "l": 38, "r": 16},
        paper_bgcolor="#0e1116",
        plot_bgcolor="#0e1116",
        font={"color": "#d1d5db", "size": 10},
        bargap=0.22,
    )
    for ann in fig.layout.annotations:
        ann.font.color = "#9aa6b2"
        ann.font.size = 10
    for axis_name in ["xaxis", "xaxis2", "xaxis3", "xaxis4"]:
        ax = getattr(fig.layout, axis_name, None)
        if ax:
            ax.update(
                showgrid=False,
                tickfont={"size": 8, "color": "#6b7280"},
                tickangle=-35,
            )
    for axis_name in ["yaxis", "yaxis2", "yaxis3", "yaxis4"]:
        ax = getattr(fig.layout, axis_name, None)
        if ax:
            ax.update(
                showgrid=True,
                gridcolor="rgba(148,163,184,0.10)",
                zeroline=False,
                tickfont={"size": 9, "color": "#9ca3af"},
                nticks=4,
            )

    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    _render_sequence_metrics(op_diag)


def _render_sequence_metrics(op_diag: OperatorDiagnostics) -> None:
    proximity_pct = min(100, int(op_diag.singular_proximity * 100))
    color_proximity = (
        "#7aa879" if proximity_pct < 40 else "#d99a52" if proximity_pct < 75 else "#d66a5f"
    )
    noncomm = op_diag.non_commutativity_score
    cr = op_diag.compression_ratio

    st.markdown(
        (
            '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin:10px 0 6px 0;">'
            f'<div style="background:#111827;border:1px solid #2a3342;border-radius:8px;padding:10px 12px;">'
            f'<div style="font-size:10px;color:#8b95a5;text-transform:uppercase;letter-spacing:.06em;">Singular Proximity</div>'
            f'<div style="font-size:22px;font-weight:700;color:{color_proximity};margin-top:4px;">{proximity_pct}%</div>'
            f'<div style="font-size:10px;color:#6b7280;margin-top:2px;">{op_diag.singular_pressure:.3f} / threshold</div>'
            '</div>'
            f'<div style="background:#111827;border:1px solid #2a3342;border-radius:8px;padding:10px 12px;">'
            f'<div style="font-size:10px;color:#8b95a5;text-transform:uppercase;letter-spacing:.06em;">Non-Commutativity</div>'
            f'<div style="font-size:22px;font-weight:700;color:#9aa6b2;margin-top:4px;">{noncomm:.3f}</div>'
            f'<div style="font-size:10px;color:#6b7280;margin-top:2px;">{op_diag.irreversible_count}/{op_diag.operator_count} irreversible</div>'
            '</div>'
            f'<div style="background:#111827;border:1px solid #2a3342;border-radius:8px;padding:10px 12px;">'
            f'<div style="font-size:10px;color:#8b95a5;text-transform:uppercase;letter-spacing:.06em;">Compression Ratio</div>'
            f'<div style="font-size:22px;font-weight:700;color:#56a3a6;margin-top:4px;">{cr:.3f}</div>'
            f'<div style="font-size:10px;color:#6b7280;margin-top:2px;">{op_diag.compressive_count} compressive ops</div>'
            '</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )
