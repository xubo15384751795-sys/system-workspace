from __future__ import annotations

from dataclasses import asdict
from html import escape
from typing import Any, Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from src.core.models import Snapshot
from src.simulation.agent_based_lab import AgentBasedLab, ToyABMScenario


CHANNELS = ("M", "D", "K", "X")
CHANNEL_LABELS = {
    "M": "M_t",
    "D": "D_t",
    "K": "K_t",
    "X": "X_t^agg",
}
CHANNEL_LONG = {
    "M": "Anchor mismatch",
    "D": "Degrees of freedom",
    "K": "Curvature",
    "X": "Aggregate shadow load",
}
CHANNEL_COLORS = {
    "M": "#3268a8",
    "D": "#2a9d8f",
    "K": "#b7791f",
    "X": "#7c3aed",
}

CASE_LIBRARY = {
    "March 2020 Treasury stress": {
        "window": ("2020-02-15", "2020-04-30"),
        "chain": "Xagg up -> M up -> D down -> K up",
        "events": [
            ("2020-03-03", "Emergency Fed cut"),
            ("2020-03-09", "Oil shock and global risk-off"),
            ("2020-03-12", "Treasury liquidity dislocation"),
            ("2020-03-15", "Zero lower bound and QE restart"),
            ("2020-03-23", "Broad Fed facilities announced"),
        ],
        "scenario": ToyABMScenario(
            steps=76,
            seed=2020,
            initial_leverage=5.5,
            target_leverage=6.4,
            leverage_adjustment_speed=0.28,
            funding_stress=0.86,
            collateral_shock=0.22,
            network_concentration=0.78,
            dealer_capacity=0.44,
            policy_delay=20,
            policy_backstop_strength=0.62,
            shadow_accumulation_speed=0.38,
        ),
    },
    "March 2023 SVB": {
        "window": ("2023-02-15", "2023-04-15"),
        "chain": "M up -> Xagg up -> D down -> K up",
        "events": [
            ("2023-03-08", "SVB securities sale and capital raise"),
            ("2023-03-10", "SVB closure"),
            ("2023-03-12", "Systemic risk exception"),
            ("2023-03-13", "BTFP operational response"),
            ("2023-03-22", "FOMC repricing"),
        ],
        "scenario": ToyABMScenario(
            steps=60,
            seed=2023,
            initial_leverage=4.2,
            target_leverage=5.2,
            leverage_adjustment_speed=0.20,
            funding_stress=0.72,
            collateral_shock=0.16,
            network_concentration=0.64,
            dealer_capacity=0.58,
            policy_delay=12,
            policy_backstop_strength=0.54,
            shadow_accumulation_speed=0.44,
        ),
    },
    "1998 LTCM": {
        "window": ("1998-08-01", "1998-10-31"),
        "chain": "M up -> K up -> D down -> coordinated backstop",
        "events": [
            ("1998-08-17", "Russia devaluation and default"),
            ("1998-09-01", "Convergence trades de-anchor"),
            ("1998-09-23", "LTCM private-sector recapitalization"),
            ("1998-09-29", "Fed easing begins"),
        ],
        "scenario": ToyABMScenario(
            steps=64,
            seed=1998,
            initial_leverage=11.0,
            target_leverage=13.0,
            leverage_adjustment_speed=0.32,
            funding_stress=0.60,
            collateral_shock=0.14,
            network_concentration=0.88,
            dealer_capacity=0.45,
            policy_delay=18,
            policy_backstop_strength=0.46,
            shadow_accumulation_speed=0.34,
        ),
    },
    "2008 Lehman": {
        "window": ("2008-08-01", "2008-11-30"),
        "chain": "Xagg up -> D down -> K up -> forced realization",
        "events": [
            ("2008-09-07", "GSE conservatorship"),
            ("2008-09-15", "Lehman bankruptcy"),
            ("2008-09-16", "AIG rescue"),
            ("2008-10-03", "TARP enacted"),
            ("2008-10-08", "Coordinated rate cuts"),
        ],
        "scenario": ToyABMScenario(
            steps=92,
            seed=2008,
            initial_leverage=7.0,
            target_leverage=8.2,
            leverage_adjustment_speed=0.24,
            funding_stress=0.82,
            collateral_shock=0.30,
            network_concentration=0.86,
            dealer_capacity=0.50,
            policy_delay=28,
            policy_backstop_strength=0.40,
            shadow_accumulation_speed=0.48,
        ),
    },
}


def inject_academic_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --paper-ink: #172033;
          --paper-muted: #667085;
          --paper-rule: #d9dee8;
          --paper-panel: #ffffff;
          --paper-soft: #f6f8fb;
          --paper-accent: #295b8f;
        }
        .stApp { background: #f7f8fb; color: var(--paper-ink); }
        [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--paper-rule); }
        h1, h2, h3 { font-family: Georgia, 'Times New Roman', serif; letter-spacing: 0; color: var(--paper-ink); }
        div, p, span, label, input, button { letter-spacing: 0 !important; }
        .paper-topline {
          border-bottom: 1px solid var(--paper-rule);
          padding: 10px 0 14px 0;
          margin-bottom: 18px;
        }
        .paper-kicker {
          color: var(--paper-muted);
          font-size: 12px;
          text-transform: uppercase;
          font-weight: 700;
        }
        .paper-title {
          font-family: Georgia, 'Times New Roman', serif;
          font-size: clamp(26px, 3vw, 40px);
          font-weight: 650;
          line-height: 1.08;
          color: var(--paper-ink);
          margin-top: 4px;
        }
        .paper-subtitle {
          max-width: 920px;
          color: var(--paper-muted);
          font-size: 14px;
          line-height: 1.55;
          margin-top: 8px;
        }
        .paper-panel {
          background: var(--paper-panel);
          border: 1px solid var(--paper-rule);
          border-radius: 8px;
          padding: 16px;
        }
        .paper-caption {
          color: #586174;
          font-size: 12px;
          line-height: 1.45;
          margin-top: 7px;
        }
        .paper-badge {
          display: inline-flex;
          align-items: center;
          border-radius: 999px;
          border: 1px solid var(--paper-rule);
          padding: 3px 9px;
          background: #fff;
          color: #344054;
          font-size: 11px;
          font-weight: 700;
          white-space: nowrap;
        }
        .paper-metric {
          background: #ffffff;
          border: 1px solid var(--paper-rule);
          border-radius: 8px;
          padding: 13px 14px;
          min-height: 124px;
        }
        .paper-metric-label {
          color: #596274;
          font-size: 12px;
          font-weight: 700;
        }
        .paper-metric-value {
          color: var(--paper-ink);
          font-family: Georgia, 'Times New Roman', serif;
          font-size: 31px;
          line-height: 1.05;
          margin-top: 8px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        (
            '<div class="paper-topline">'
            f'<div class="paper-kicker">{escape(kicker)}</div>'
            f'<div class="paper-title">{escape(title)}</div>'
            f'<div class="paper-subtitle">{escape(subtitle)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_evidence_badge(snapshot: Snapshot | None) -> None:
    label, color = evidence_quality(snapshot)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    st.markdown(
        (
            '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px;">'
            f'<span class="paper-badge">Current date: {today}</span>'
            f'<span class="paper-badge" style="border-color:{color};color:{color};">Evidence quality: {label}</span>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def evidence_quality(snapshot: Snapshot | None) -> tuple[str, str]:
    if snapshot is None:
        return "missing", "#b42318"
    available = sum(1 for channel in CHANNELS if bool(snapshot.proxy.available.get(channel, False)))
    if snapshot.escalation:
        return "review required", "#b42318"
    if available >= 4:
        return "high", "#287d55"
    if available >= 2:
        return "medium", "#a15c00"
    return "low", "#b42318"


def regime_status(snapshot: Snapshot) -> tuple[str, str, str]:
    sigma = float(snapshot.state.sigma_t or 0.0)
    if bool(snapshot.state.singular_flag) or sigma >= 2.0:
        return "singular candidate", "#b42318", "State is inside or near the paper's singular region."
    if sigma >= 1.0:
        return "elevated", "#a15c00", "Stress is elevated but does not satisfy singular-region conditions."
    return "normal", "#287d55", "Current channel readings are locally contained."


def render_metric_cards(snapshot: Snapshot, history: pd.DataFrame) -> None:
    cols = st.columns(4)
    for col, channel in zip(cols, CHANNELS):
        value = getattr(snapshot.proxy, channel, None)
        spark = history[["date", channel]].tail(30).dropna() if not history.empty else pd.DataFrame()
        with col:
            st.markdown(
                (
                    '<div class="paper-metric">'
                    f'<div class="paper-metric-label">{CHANNEL_LABELS[channel]} · {CHANNEL_LONG[channel]}</div>'
                    f'<div class="paper-metric-value">{format_value(value)}</div>'
                    f'<div style="margin-top:8px;color:#667085;font-size:11px;">past 30 observations</div>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            if len(spark) >= 2:
                fig = go.Figure(
                    go.Scatter(
                        x=spark["date"],
                        y=spark[channel],
                        mode="lines",
                        line={"color": CHANNEL_COLORS[channel], "width": 1.8},
                        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
                    )
                )
                fig.update_layout(
                    height=76,
                    margin={"t": 4, "b": 4, "l": 2, "r": 2},
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis={"visible": False},
                    yaxis={"visible": False},
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            else:
                st.caption("Trend unavailable.")


def render_regime_callout(snapshot: Snapshot) -> None:
    label, color, note = regime_status(snapshot)
    st.markdown(
        (
            '<div class="paper-panel" style="display:flex;justify-content:space-between;gap:16px;align-items:center;">'
            '<div>'
            '<div class="paper-kicker">Regime Status</div>'
            f'<div style="font-family:Georgia,serif;font-size:30px;color:{color};line-height:1.1;margin-top:5px;">'
            f"{escape(label)}</div>"
            f'<div class="paper-caption">{escape(note)}</div>'
            "</div>"
            f'<div class="paper-badge" style="border-color:{color};color:{color};">Sigma {format_value(snapshot.state.sigma_t)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_phase_diagram(history: pd.DataFrame, snapshot: Snapshot) -> None:
    frame = history.copy()
    if frame.empty:
        frame = pd.DataFrame(
            [{"date": pd.to_datetime(snapshot.run_date), "D": snapshot.proxy.D, "K": snapshot.proxy.K, "sigma_t": snapshot.state.sigma_t}]
        )
    fig = go.Figure()
    x_min, x_max = _range_with_padding(frame["D"], fallback=(-1.0, 1.0))
    y_min, y_max = _range_with_padding(frame["K"], fallback=(-0.2, 1.2))
    fig.add_shape(
        type="rect",
        x0=x_min,
        x1=min(-0.65, x_max),
        y0=max(0.65, y_min),
        y1=y_max,
        fillcolor="rgba(180, 35, 24, 0.13)",
        line={"width": 0},
        layer="below",
    )
    fig.add_trace(
        go.Scatter(
            x=frame["D"],
            y=frame["K"],
            mode="lines+markers",
            marker={
                "size": 6,
                "color": frame["sigma_t"].fillna(0),
                "colorscale": "Cividis",
                "showscale": True,
                "colorbar": {"title": "Sigma", "thickness": 12},
            },
            line={"color": "rgba(41, 91, 143, 0.45)", "width": 1.4},
            text=frame["date"].dt.strftime("%Y-%m-%d") if "date" in frame else None,
            hovertemplate="date=%{text}<br>D=%{x:.3f}<br>K=%{y:.3f}<extra></extra>",
            name="trajectory",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[snapshot.proxy.D],
            y=[snapshot.proxy.K],
            mode="markers",
            marker={"size": 15, "color": "#b42318", "symbol": "circle-open", "line": {"width": 3}},
            hovertemplate="current<br>D=%{x:.3f}<br>K=%{y:.3f}<extra></extra>",
            name="current",
        )
    )
    fig.add_vline(x=-0.65, line_dash="dot", line_color="rgba(102,112,133,.7)")
    fig.add_hline(y=0.65, line_dash="dot", line_color="rgba(102,112,133,.7)")
    fig.add_annotation(
        x=x_min,
        y=y_max,
        text="singular region",
        showarrow=False,
        xanchor="left",
        yanchor="top",
        font={"size": 12, "color": "#8a2d23"},
    )
    fig.update_layout(
        height=440,
        margin={"t": 24, "b": 36, "l": 48, "r": 20},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#172033", "size": 12},
        xaxis_title="D_t · effective degrees of freedom",
        yaxis_title="K_t · curvature",
        showlegend=False,
    )
    fig.update_xaxes(showgrid=True, gridcolor="#e6eaf1", zeroline=True, zerolinecolor="#cfd6e3")
    fig.update_yaxes(showgrid=True, gridcolor="#e6eaf1", zeroline=True, zerolinecolor="#cfd6e3")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<div class="paper-caption">Figure 4 analogue. The shaded quadrant marks low D_t and high K_t, '
        "where structural singularity becomes a candidate rather than a point forecast.</div>",
        unsafe_allow_html=True,
    )


def render_shadow_maturity(snapshot: Snapshot) -> None:
    buckets = shadow_buckets(snapshot)
    fig = go.Figure(
        go.Bar(
            x=[item["bucket"] for item in buckets],
            y=[item["mass"] for item in buckets],
            marker_color=[item["color"] for item in buckets],
            hovertemplate="%{x}<br>mass=%{y:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=270,
        margin={"t": 10, "b": 35, "l": 38, "r": 12},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#172033", "size": 11},
        yaxis_title="mass",
        xaxis_title=None,
    )
    fig.update_yaxes(gridcolor="#e6eaf1")
    fig.update_xaxes(showgrid=False)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<div class="paper-caption">Interpret as the maturity distribution of latent pressure. '
        "A front-loaded profile makes fast realization more plausible.</div>",
        unsafe_allow_html=True,
    )


def render_signature_quantities(snapshot: Snapshot) -> None:
    op_diag = snapshot.state.operator_diagnostics
    noncomm = float(op_diag.non_commutativity_score) if op_diag else 0.0
    gap_state = snapshot.state.mean_field_gap
    gap = float(gap_state.normalized_gap if gap_state else 0.0)
    peak = max(item["mass"] for item in shadow_buckets(snapshot))
    cols = st.columns(3)
    for col, title, value in [
        (cols[0], "Non-commutativity score", noncomm),
        (cols[1], "Mean-field gap", gap),
        (cols[2], "Shadow maturity peak", peak),
    ]:
        level, color = contextual_level(value)
        with col:
            st.markdown(
                (
                    '<div class="paper-panel">'
                    f'<div class="paper-kicker">{escape(title)}</div>'
                    f'<div style="font-family:Georgia,serif;font-size:30px;margin-top:6px;">{value:.3f}</div>'
                    f'<span class="paper-badge" style="border-color:{color};color:{color};">{level}</span>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )


def render_history_panels(history: pd.DataFrame) -> None:
    if history.empty:
        st.info("No snapshot history yet.")
        return
    fig = make_subplots(
        rows=4,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        subplot_titles=[f"{CHANNEL_LABELS[c]} · {CHANNEL_LONG[c]}" for c in CHANNELS],
    )
    for row, channel in enumerate(CHANNELS, start=1):
        fig.add_trace(
            go.Scatter(
                x=history["date"],
                y=history[channel],
                mode="lines",
                line={"color": CHANNEL_COLORS[channel], "width": 1.8},
                hovertemplate=f"{channel}<br>%{{x|%Y-%m-%d}}<br>%{{y:.3f}}<extra></extra>",
                connectgaps=True,
            ),
            row=row,
            col=1,
        )
    _style_time_figure(fig, height=620)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<div class="paper-caption">Panel 1. Four-channel structural trajectory. '
        "Read levels jointly; the framework is about channel composition, not univariate alarms.</div>",
        unsafe_allow_html=True,
    )


def render_stress_panel(history: pd.DataFrame) -> None:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=history["date"],
            y=history["sigma_t"],
            mode="lines",
            fill="tozeroy",
            line={"color": "#295b8f", "width": 1.8},
            fillcolor="rgba(41,91,143,0.16)",
            hovertemplate="Sigma<br>%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
        )
    )
    singular = history[history["singular_flag"].fillna(False).astype(bool)]
    if not singular.empty:
        fig.add_trace(
            go.Scatter(
                x=singular["date"],
                y=singular["sigma_t"],
                mode="markers",
                marker={"color": "#b42318", "size": 9, "symbol": "diamond"},
                name="singular indicator",
            )
        )
    fig.add_hline(y=2.0, line_dash="dot", line_color="#b42318")
    fig.update_layout(
        height=330,
        margin={"t": 16, "b": 34, "l": 42, "r": 18},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#172033", "size": 12},
        showlegend=False,
        yaxis_title="Sigma_t",
    )
    fig.update_xaxes(gridcolor="#e6eaf1")
    fig.update_yaxes(gridcolor="#e6eaf1")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<div class="paper-caption">Panel 2. Joint stress score with singular indicator overlay. '
        "The dotted threshold is an interpretive guide, not an econometric confidence interval.</div>",
        unsafe_allow_html=True,
    )


def render_shadow_heatmap(history: pd.DataFrame) -> None:
    rows = []
    for _, row in history.iterrows():
        pseudo = shadow_profile_from_values(row.get("X"), row.get("K"), row.get("D"))
        for bucket in pseudo:
            rows.append({"date": row["date"], "bucket": bucket["bucket"], "mass": bucket["mass"]})
    frame = pd.DataFrame.from_records(rows)
    fig = go.Figure(
        go.Heatmap(
            x=frame["date"],
            y=frame["bucket"],
            z=frame["mass"],
            colorscale="Viridis",
            colorbar={"title": "mass", "thickness": 12},
            hovertemplate="%{x|%Y-%m-%d}<br>%{y}<br>mass=%{z:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=310,
        margin={"t": 12, "b": 38, "l": 72, "r": 20},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#172033", "size": 12},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<div class="paper-caption">Panel 3. Shadow maturity profile over time. '
        "Where persisted bucket data are absent, the UI derives a stable display proxy from X, K, and D.</div>",
        unsafe_allow_html=True,
    )


def render_mean_field_gap(history: pd.DataFrame) -> None:
    work = history.copy()
    work["gap"] = (work["X"].fillna(0).abs() * work["K"].fillna(0).abs()).rolling(3, min_periods=1).mean()
    fig = go.Figure(
        go.Scatter(
            x=work["date"],
            y=work["gap"],
            mode="lines",
            line={"color": "#7c3aed", "width": 1.8},
            hovertemplate="%{x|%Y-%m-%d}<br>gap=%{y:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=280,
        margin={"t": 12, "b": 34, "l": 42, "r": 16},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#172033", "size": 12},
        yaxis_title="G_t^mf",
    )
    fig.update_xaxes(gridcolor="#e6eaf1")
    fig.update_yaxes(gridcolor="#e6eaf1")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_case_replay(case_name: str) -> None:
    case = CASE_LIBRARY[case_name]
    frame = simulate_case(case_name)
    start, end = pd.to_datetime(case["window"][0]), pd.to_datetime(case["window"][1])
    frame = frame.copy()
    frame["date"] = pd.date_range(start, end, periods=len(frame))
    summary = case_summary(frame)

    cols = st.columns([1.1, 1.9], gap="large")
    with cols[0]:
        st.markdown('<div class="paper-panel">', unsafe_allow_html=True)
        st.markdown("#### Case Timeline")
        timeline = pd.DataFrame(case["events"], columns=["date", "event"])
        st.dataframe(timeline, use_container_width=True, hide_index=True)
        st.markdown(f"**Mechanism chain:** `{case['chain']}`")
        st.markdown(
            f'<div class="paper-caption">Regime summary: max Sigma {summary["max_sigma"]:.2f}; '
            f'first singular contact {summary["first_singular"]}.</div>',
            unsafe_allow_html=True,
        )
        st.markdown("</div>", unsafe_allow_html=True)
    with cols[1]:
        render_case_channels(frame, case["events"])
    render_mechanism_chain(case["chain"])


def render_case_channels(frame: pd.DataFrame, events: Iterable[tuple[str, str]]) -> None:
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.045, subplot_titles=list(CHANNEL_LABELS.values()))
    for row, channel in enumerate(CHANNELS, start=1):
        fig.add_trace(
            go.Scatter(
                x=frame["date"],
                y=frame[channel],
                mode="lines",
                line={"color": CHANNEL_COLORS[channel], "width": 1.8},
                hovertemplate=f"{channel}<br>%{{x|%Y-%m-%d}}<br>%{{y:.3f}}<extra></extra>",
            ),
            row=row,
            col=1,
        )
        for event_date, label in events:
            fig.add_vline(x=pd.to_datetime(event_date), line_dash="dot", line_color="rgba(102,112,133,.55)", row=row, col=1)
    _style_time_figure(fig, height=620)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<div class="paper-caption">Case replay. Event annotations are aligned to the structural state path, '
        "so the narrative chain can be inspected against M, D, K, and X directly.</div>",
        unsafe_allow_html=True,
    )


def render_mechanism_chain(chain: str) -> None:
    parts = [part.strip() for part in chain.replace("->", "→").split("→")]
    html = "".join(
        f'<span class="paper-badge" style="margin-right:7px;margin-bottom:7px;">{escape(part)}</span>'
        + ("" if idx == len(parts) - 1 else '<span style="color:#667085;margin-right:7px;">→</span>')
        for idx, part in enumerate(parts)
    )
    st.markdown('<div class="paper-panel"><div class="paper-kicker">Mechanism Chain</div><div style="margin-top:10px;">' + html + "</div></div>", unsafe_allow_html=True)


def render_scenario_lab() -> None:
    scenario_type = st.sidebar.selectbox(
        "Scenario type",
        ["Leverage shock", "Funding stress", "Collateral squeeze", "Run dynamics", "Policy intervention"],
        key="scenario_type",
    )
    params = scenario_defaults(scenario_type)
    st.sidebar.markdown("### Parameters")
    params["funding_stress"] = st.sidebar.slider("Funding stress", 0.0, 1.0, params["funding_stress"], 0.01)
    params["collateral_shock"] = st.sidebar.slider("Collateral squeeze", 0.0, 0.6, params["collateral_shock"], 0.01)
    params["initial_leverage"] = st.sidebar.slider("Initial leverage", 1.0, 14.0, params["initial_leverage"], 0.1)
    params["network_concentration"] = st.sidebar.slider("Network concentration", 0.0, 1.0, params["network_concentration"], 0.01)
    params["policy_backstop_strength"] = st.sidebar.slider("Policy backstop", 0.0, 1.0, params["policy_backstop_strength"], 0.01)
    scenario = ToyABMScenario(**params)
    frame = AgentBasedLab().simulate(scenario)

    render_scenario_summary(frame)
    render_case_channels(frame.assign(date=pd.RangeIndex(len(frame))), [])
    render_scenario_mechanisms(frame)


def render_operator_sequence(snapshot: Snapshot | None, include_exploratory: bool = False) -> None:
    if snapshot is None or snapshot.state.operator_diagnostics is None:
        st.info("No operator diagnostics available for the selected snapshot.")
        return
    op_diag = snapshot.state.operator_diagnostics
    apps = list(op_diag.applications)
    if not apps:
        st.info("No operators applied in current window.")
        return
    rows = []
    for idx, app in enumerate(apps, start=1):
        rows.append(
            {
                "step": idx,
                "date": app.event_date or "-",
                "operator": app.operator_name,
                "family": app.family,
                "intensity": app.intensity,
                "dM": app.delta.get("M", 0.0),
                "dD": app.delta.get("D", 0.0),
                "dK": app.delta.get("K", 0.0),
                "dX": app.delta.get("X", 0.0),
            }
        )
    frame = pd.DataFrame.from_records(rows)
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if include_exploratory:
        cols = st.columns(3)
        cols[0].metric("Non-commutativity", f"{op_diag.non_commutativity_score:.3f}")
        cols[1].metric("Path-rank witnesses", str(op_diag.path_rank_witness_count))
        cols[2].metric("Max output separation", f"{op_diag.path_rank_max_output_separation:.3f}")
        st.caption("Path-rank witness metrics are exploratory finite-sequence proxies, not the full paper condition.")
    else:
        cols = st.columns(3)
        cols[0].metric("Non-commutativity", f"{op_diag.non_commutativity_score:.3f}")
        cols[1].metric("Singular proximity", f"{op_diag.singular_proximity:.3f}")
        cols[2].metric("Compression ratio", f"{op_diag.compression_ratio:.3f}")
    render_lie_bracket_proxy(frame)


def render_lie_bracket_proxy(frame: pd.DataFrame) -> None:
    fig = go.Figure()
    fig.add_trace(
        go.Cone(
            x=frame["step"],
            y=np.zeros(len(frame)),
            z=np.zeros(len(frame)),
            u=frame["dM"],
            v=frame["dD"],
            w=frame["dK"] + frame["dX"],
            colorscale="Cividis",
            sizemode="absolute",
            sizeref=0.22,
            showscale=False,
            hovertemplate="step=%{x}<br>dM=%{u:.3f}<br>dD=%{v:.3f}<br>dK+dX=%{w:.3f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=420,
        margin={"t": 8, "b": 8, "l": 8, "r": 8},
        paper_bgcolor="#ffffff",
        scene={
            "xaxis_title": "event step",
            "yaxis_title": "D response",
            "zaxis_title": "K/X response",
            "bgcolor": "#ffffff",
        },
    )
    st.plotly_chart(fig, use_container_width=True)
    st.markdown(
        '<div class="paper-caption">Lie-bracket proxy view. Vectors summarize ordered channel response; '
        "large directional disagreement is where commutator inspection becomes useful.</div>",
        unsafe_allow_html=True,
    )


def render_evidence_table(snapshot: Snapshot | None, ctx: Any) -> None:
    if snapshot is None:
        st.info("No snapshot available.")
        return
    provenance = dict(snapshot.state.provenance or {})
    rows = []
    for channel in CHANNELS:
        rows.append(
            {
                "channel": channel,
                "proxy basket": provenance.get(f"{channel}_source", provenance.get("source", "pipeline composite")),
                "available": bool(snapshot.proxy.available.get(channel, False)),
                "direction": snapshot.proxy.directions.get(channel, "UNKNOWN"),
                "value": getattr(snapshot.proxy, channel, None),
                "quality": evidence_quality(snapshot)[0],
                "fallback": provenance.get("fallback_status", "not reported"),
            }
        )
    st.dataframe(pd.DataFrame.from_records(rows), use_container_width=True, hide_index=True)

    st.markdown("#### Calibration and Thresholds")
    thresholds = ctx.config.get("thresholds", {}) if hasattr(ctx, "config") else {}
    threshold_rows = [{"name": key, "value": value} for key, value in dict(thresholds).items()]
    if threshold_rows:
        st.dataframe(pd.DataFrame.from_records(threshold_rows), use_container_width=True, hide_index=True)
    else:
        st.caption("No threshold block found in config.")

    st.markdown("#### Snapshot Provenance")
    st.json(provenance)


def shadow_buckets(snapshot: Snapshot) -> list[dict[str, Any]]:
    state = snapshot.state.shadow_mass_state
    if state is not None and state.buckets:
        return [
            {
                "bucket": bucket.name or bucket.horizon,
                "mass": float(bucket.mass),
                "color": "#31688e",
            }
            for bucket in state.buckets
        ]
    return shadow_profile_from_values(snapshot.proxy.X, snapshot.proxy.K, snapshot.proxy.D)


def shadow_profile_from_values(x_value: Any, k_value: Any, d_value: Any) -> list[dict[str, Any]]:
    x = max(0.0, float(x_value or 0.0))
    k = max(0.0, float(k_value or 0.0))
    d_pressure = max(0.0, -float(d_value or 0.0))
    total = max(0.05, x + 0.35 * k + 0.25 * d_pressure)
    weights = np.array([0.26 + d_pressure, 0.32 + k, 0.26 + x, 0.16 + 0.5 * x])
    weights = weights / weights.sum()
    labels = ["0-30d", "31-90d", "91-180d", "180d+"]
    colors = ["#440154", "#31688e", "#35b779", "#fde725"]
    return [{"bucket": label, "mass": float(total * weight), "color": color} for label, weight, color in zip(labels, weights, colors)]


def contextual_level(value: float) -> tuple[str, str]:
    if value >= 0.75:
        return "high", "#b42318"
    if value >= 0.35:
        return "medium", "#a15c00"
    return "low", "#287d55"


def format_value(value: Any) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not np.isfinite(numeric):
        return "-"
    return f"{numeric:.2f}"


def _range_with_padding(series: pd.Series, fallback: tuple[float, float]) -> tuple[float, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return fallback
    lo, hi = float(clean.min()), float(clean.max())
    if abs(hi - lo) < 1e-9:
        return lo - 0.5, hi + 0.5
    pad = 0.18 * (hi - lo)
    return lo - pad, hi + pad


def _style_time_figure(fig: go.Figure, height: int) -> None:
    fig.update_layout(
        height=height,
        margin={"t": 34, "b": 34, "l": 42, "r": 18},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font={"color": "#172033", "size": 12},
        showlegend=False,
        hovermode="x unified",
    )
    fig.update_xaxes(gridcolor="#e6eaf1", zeroline=False)
    fig.update_yaxes(gridcolor="#e6eaf1", zeroline=False, nticks=4)
    for ann in fig.layout.annotations:
        ann.font.size = 12
        ann.font.color = "#344054"


@st.cache_data(show_spinner=False)
def simulate_case(case_name: str) -> pd.DataFrame:
    scenario = CASE_LIBRARY[case_name]["scenario"]
    return AgentBasedLab().simulate(scenario)


def case_summary(frame: pd.DataFrame) -> dict[str, Any]:
    singular = frame["singular_flag"].astype(bool)
    first = "-"
    if singular.any():
        first_row = frame.loc[singular].iloc[0]
        first = pd.to_datetime(first_row["date"]).strftime("%Y-%m-%d") if "date" in frame else str(first_row["step"])
    return {"max_sigma": float(frame["Sigma"].max()), "first_singular": first}


def scenario_defaults(scenario_type: str) -> dict[str, Any]:
    base = asdict(ToyABMScenario(steps=72, seed=11))
    if scenario_type == "Leverage shock":
        base.update(initial_leverage=8.0, target_leverage=9.0, funding_stress=0.45)
    elif scenario_type == "Funding stress":
        base.update(funding_stress=0.78, dealer_capacity=0.55)
    elif scenario_type == "Collateral squeeze":
        base.update(collateral_shock=0.32, funding_stress=0.55)
    elif scenario_type == "Run dynamics":
        base.update(funding_stress=0.82, network_concentration=0.82, shadow_accumulation_speed=0.55)
    elif scenario_type == "Policy intervention":
        base.update(funding_stress=0.70, policy_delay=10, policy_backstop_strength=0.60)
    return base


def render_scenario_summary(frame: pd.DataFrame) -> None:
    summary = AgentBasedLab().summarize(frame)
    cols = st.columns(4)
    cols[0].metric("Singular probability", f"{summary.singular_probability:.1%}")
    cols[1].metric("Max Sigma", f"{summary.max_sigma:.2f}")
    cols[2].metric("Max mean-field gap", f"{summary.max_mean_field_gap:.2f}")
    first = "-" if summary.first_singular_step is None else str(summary.first_singular_step)
    cols[3].metric("First singular step", first)


def render_scenario_mechanisms(frame: pd.DataFrame) -> None:
    fig = make_subplots(rows=1, cols=3, subplot_titles=["Leverage", "Dealer capacity", "Hidden load"])
    for col, name, color in [(1, "leverage", "#295b8f"), (2, "dealer_capacity", "#2a9d8f"), (3, "hidden_load", "#7c3aed")]:
        fig.add_trace(go.Scatter(x=frame["step"], y=frame[name], mode="lines", line={"color": color}), row=1, col=col)
    fig.update_layout(
        height=300,
        margin={"t": 32, "b": 30, "l": 34, "r": 12},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        showlegend=False,
    )
    fig.update_xaxes(gridcolor="#e6eaf1")
    fig.update_yaxes(gridcolor="#e6eaf1")
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
