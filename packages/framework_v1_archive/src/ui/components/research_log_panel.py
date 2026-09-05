from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from src.ui.components.snapshot_readout import render_snapshot_readout
from src.ui.helpers.coupling_view import COUPLING_BAND_MEANINGS, coupling_bands, coupling_codes, proxy_corr
from src.ui.helpers.ui_runtime import history_frame, list_snapshots, snapshot_archive_frame


ACTORS = ["CENTRAL_BANK", "REGULATOR", "CLO_MANAGER", "VC_FUND", "MACRO_INVESTOR"]
EXPECTED = ["IMPROVING", "WORSENING"]
PROXIES = ["M", "D", "K", "X"]
PROXY_COLORS = {"M": "#d66a5f", "D": "#d99a52", "K": "#56a3a6", "X": "#6b83c7"}
FAMILY_COLORS = {
    "compression": "#d66a5f",
    "curvature": "#d99a52",
    "shadow_transfer": "#6b83c7",
    "realization": "#c84b6e",
    "intervention": "#7aa879",
    "mechanism": "#9aa6b2",
    "unknown": "rgba(118,130,148,0.55)",
}
PROXY_FULL_NAMES = {
    "M": "Anchor Mismatch",
    "D": "Degrees of Freedom",
    "K": "Transition Curvature",
    "X": "Shadow Pressure",
}
COUPLING_BAND_COLORS = {
    "Inverse Coupling": "#7a3138",
    "Tension": "#806338",
    "Decoupled": "#2b3038",
    "Coupled": "#2f6764",
    "Synchronized": "#3d7a52",
    "Self": "#2b3038",
}
COUPLING_COLORSCALE = [
    [0.0, COUPLING_BAND_COLORS["Inverse Coupling"]],
    [0.199, COUPLING_BAND_COLORS["Inverse Coupling"]],
    [0.2, COUPLING_BAND_COLORS["Tension"]],
    [0.399, COUPLING_BAND_COLORS["Tension"]],
    [0.4, COUPLING_BAND_COLORS["Decoupled"]],
    [0.599, COUPLING_BAND_COLORS["Decoupled"]],
    [0.6, COUPLING_BAND_COLORS["Coupled"]],
    [0.799, COUPLING_BAND_COLORS["Coupled"]],
    [0.8, COUPLING_BAND_COLORS["Synchronized"]],
    [1.0, COUPLING_BAND_COLORS["Synchronized"]],
]
COUPLING_CELL_LABELS = {
    "Inverse Coupling": "Inverse<br>Coupling",
    "Tension": "Tension",
    "Decoupled": "Decoupled",
    "Coupled": "Coupled",
    "Synchronized": "Synchronized",
    "Self": "Self",
}
COUPLING_LEGEND_ORDER = ["Inverse Coupling", "Tension", "Decoupled", "Coupled", "Synchronized"]
PAIR_STRUCTURAL_CONTEXT: dict[tuple[str, str], str] = {
    ("D", "K"): "Pre-singular deformation channel.",
    ("K", "X"): "Hidden pressure becoming nonlinear.",
    ("M", "D"): "Anchor drift constraining freedom.",
    ("M", "X"): "Shadow load tied to anchor mismatch.",
    ("D", "X"): "Hidden pressure reducing degrees of freedom.",
    ("K", "M"): "Anchor slippage deforming transition maps.",
}


def render_section_label(title: str, caption: str | None = None) -> None:
    st.markdown(
        (
            '<div style="font-size:12px;color:#7f8a99;text-transform:uppercase;'
            f'letter-spacing:.08em;margin:6px 0 4px 0;">{escape(title)}</div>'
        ),
        unsafe_allow_html=True,
    )
    if caption:
        st.caption(caption)


def render_page_header(title: str, subtitle: str) -> None:
    st.markdown(
        (
            '<div style="margin:2px 0 20px 0;">'
            f'<div style="font-size:28px;font-weight:650;color:#e5e7eb;letter-spacing:0;line-height:1.15;">{escape(title)}</div>'
            f'<div style="font-size:13px;color:#8b95a5;margin-top:8px;line-height:1.35;">{escape(subtitle)}</div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def pair_context(source: str, target: str) -> str:
    if source == target:
        return str(COUPLING_BAND_MEANINGS["Self"])
    pair = (min(source, target), max(source, target))
    return str(PAIR_STRUCTURAL_CONTEXT.get(pair, "Cross-channel structural relation."))


def format_corr_value(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "unavailable"
    return f"{float(value):.2f}"


def format_proxy_readout(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "-"
    return f"{float(value):.2f}"


def latest_filtered_row(filtered: pd.DataFrame, history: pd.DataFrame) -> pd.Series | None:
    if not filtered.empty:
        return filtered.iloc[-1]
    if not history.empty:
        return history.iloc[-1]
    return None


def proxy_change_label(proxy: str, history: pd.DataFrame) -> str:
    if history.empty or proxy not in history.columns:
        return f"{proxy}: no movement available"
    series = history[["date", proxy]].dropna().tail(2)
    if len(series) < 2:
        return f"{proxy}: no movement available"
    previous = float(series.iloc[0][proxy])
    current = float(series.iloc[1][proxy])
    delta = current - previous
    if abs(delta) < 1e-9:
        direction = "held steady"
    elif delta > 0:
        direction = "rose"
    else:
        direction = "fell"
    return f"{proxy} {direction} {abs(delta):.2f} to {current:.2f}"


def structural_summary(history: pd.DataFrame, snapshot) -> list[str]:
    latest = latest_filtered_row(history, history)
    if latest is None:
        return ["No proxy movement is available in the selected window."]

    changes = [proxy_change_label(proxy, history) for proxy in PROXIES]
    stress = format_proxy_readout(getattr(snapshot.state, "sigma_t", None))
    elevated = [
        f"{proxy} {format_proxy_readout(latest.get(proxy))}"
        for proxy in PROXIES
        if pd.notna(latest.get(proxy)) and float(latest.get(proxy)) >= 0.65
    ]
    if elevated:
        elevated_text = ", ".join(elevated)
        compression = f"Elevated or compressed channels: {elevated_text}; Joint Stress {stress}."
    else:
        compression = f"No proxy channel is above the 0.65 watch band; Joint Stress {stress}."
    escalation = "Escalation is active." if snapshot.escalation else "Escalation is inactive."
    return ["Latest movement: " + "; ".join(changes[:4]) + ".", compression, escalation]


def render_structural_summary(items: list[str]) -> None:
    bullets = "".join(f"<li>{escape(item)}</li>" for item in items[:3])
    st.markdown(
        (
            '<section style="background:#0e1116;border:1px solid #273142;border-radius:8px;'
            'padding:14px 16px;margin:0 0 32px 0;color:#d1d5db;">'
            '<div style="font-size:12px;color:#7f8a99;text-transform:uppercase;letter-spacing:.08em;">Structural Summary</div>'
            f'<ul style="margin:8px 0 0 18px;padding:0;font-size:13px;line-height:1.55;color:#cbd5e1;">{bullets}</ul>'
            "</section>"
        ),
        unsafe_allow_html=True,
    )


def render_event_note(event_count: int) -> None:
    note = "No logged events inside this window." if event_count == 0 else f"{event_count} logged event window marker{'s' if event_count != 1 else ''} aligned across all proxy rows."
    st.markdown(
        (
            '<div style="display:flex;align-items:center;gap:8px;margin-top:8px;color:#8b95a5;'
            'font-size:12px;line-height:1.35;">'
            '<span style="display:inline-block;width:18px;border-top:1px dotted rgba(148,163,184,.75);"></span>'
            f"<span>{escape(note)}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def render_coupling_legend() -> None:
    items = []
    for label in COUPLING_LEGEND_ORDER:
        color = COUPLING_BAND_COLORS[label]
        items.append(
            '<span style="display:inline-flex;align-items:center;gap:6px;margin:0 14px 6px 0;'
            'font-size:11px;color:#a8b0bd;">'
            f'<span style="width:10px;height:10px;background:{color};border-radius:2px;'
            'border:1px solid rgba(229,231,235,.16);"></span>'
            f"{escape(label)}</span>"
        )
    st.markdown(
        '<div style="margin:2px 0 8px 0;">' + "".join(items) + "</div>",
        unsafe_allow_html=True,
    )


def classify_direction(from_value: float | None, to_value: float | None, eps: float = 1e-9) -> str:
    if from_value is None or to_value is None:
        return "UNKNOWN"
    delta = to_value - from_value
    if delta > eps:
        return "WORSENING"
    if delta < -eps:
        return "IMPROVING"
    return "STABLE"


def aggregate_proxy_value(row: pd.Series) -> float | None:
    values = [row.get("M"), row.get("D"), row.get("K"), row.get("X")]
    vals = [float(v) for v in values if v is not None and pd.notna(v)]
    if not vals:
        return None
    return sum(vals) / len(vals)


def direction_after_days(history: pd.DataFrame, base_date: str, days: int) -> str:
    if history.empty:
        return "UNKNOWN"
    base_ts = pd.to_datetime(base_date)
    target_ts = base_ts + timedelta(days=days)
    current = history[history["date"] <= base_ts].tail(1)
    future = history[history["date"] >= target_ts].head(1)
    if current.empty or future.empty:
        return "UNKNOWN"
    return classify_direction(aggregate_proxy_value(current.iloc[0]), aggregate_proxy_value(future.iloc[0]))


def build_reflexivity_tracker(events: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=["date", "actor", "intervention_type", "expected_direction", "affected_proxy", "description", "t30_direction", "t60_direction", "reflexivity_active"])
    work = events.copy()
    hist = history.copy()
    if not hist.empty:
        hist["date"] = pd.to_datetime(hist["date"])
    work["t30_direction"] = work["date"].apply(lambda d: direction_after_days(hist, d, 30))
    work["t60_direction"] = work["date"].apply(lambda d: direction_after_days(hist, d, 60))

    def is_active(row: pd.Series) -> bool:
        expected = str(row.get("expected_direction", "")).upper()
        t30 = str(row.get("t30_direction", "")).upper()
        t60 = str(row.get("t60_direction", "")).upper()
        if expected == "IMPROVING":
            return t30 == "WORSENING" or t60 == "WORSENING"
        if expected == "WORSENING":
            return t30 == "IMPROVING" or t60 == "IMPROVING"
        return False

    work["reflexivity_active"] = work.apply(is_active, axis=1)
    return work


def style_reflexivity_rows(row: pd.Series) -> list[str]:
    if bool(row.get("reflexivity_active")):
        return ["background-color: rgba(184, 58, 44, 0.22)"] * len(row)
    return [""] * len(row)


def render_event_form(ctx) -> None:
    st.markdown("### Event Log Entry")
    with st.form("event_log_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            event_date = st.date_input("date", value=date.today())
            actor = st.selectbox("actor", options=ACTORS)
            intervention_type = st.text_input("intervention_type", placeholder="Liquidity backstop, policy cut...")
        with c2:
            expected_direction = st.selectbox("expected_direction", options=EXPECTED)
            affected_proxy = st.multiselect("affected_proxy", options=PROXIES, default=["D"])
        description = st.text_area("description", height=100)
        submitted = st.form_submit_button("Submit Event")

    if submitted:
        event = {
            "date": event_date.strftime("%Y-%m-%d"),
            "actor": actor,
            "intervention_type": intervention_type.strip(),
            "expected_direction": expected_direction,
            "affected_proxy": affected_proxy,
            "description": description.strip(),
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        ctx.event_logger.write_event(event)
        st.success("Event logged.")


def render_event_table(ctx) -> None:
    events = ctx.event_logger.load_events()
    if events.empty:
        st.info("No events logged yet.")
    else:
        st.dataframe(events.tail(20), use_container_width=True, hide_index=True)


def render_graph_explorer(ctx) -> None:
    snapshots = list_snapshots(ctx)
    history = history_frame(snapshots)
    if history.empty:
        st.info("No snapshot history yet.")
        return
    corr = proxy_corr(history)
    bands = coupling_bands(history)
    codes = coupling_codes(history)
    text = bands.copy()
    customdata = []
    for row in bands.index:
        custom_row = []
        for col in bands.columns:
            band = str(bands.loc[row, col])
            raw = corr.loc[row, col] if row in corr.index and col in corr.columns else None
            text.loc[row, col] = COUPLING_CELL_LABELS.get(band, band)
            custom_row.append(
                [
                    COUPLING_BAND_MEANINGS.get(band, ""),
                    pair_context(str(row), str(col)),
                    format_corr_value(raw),
                ]
            )
        customdata.append(custom_row)
    fig = go.Figure(
        data=go.Heatmap(
            z=codes.fillna(0).values,
            x=codes.columns,
            y=codes.index,
            text=text.values,
            texttemplate="%{text}",
            customdata=customdata,
            colorscale=COUPLING_COLORSCALE,
            zmin=-2.5,
            zmax=2.5,
            showscale=False,
            hovertemplate=(
                "<b>%{y} / %{x}</b><br>"
                "%{customdata[0]}<br>"
                "%{customdata[1]}<br>"
                "Raw correlation input: %{customdata[2]}<extra></extra>"
            ),
            xgap=2,
            ygap=2,
        )
    )
    fig.update_layout(
        height=420,
        margin={"t": 18, "b": 18, "l": 18, "r": 18},
        title=None,
        paper_bgcolor="#0e1116",
        plot_bgcolor="#0e1116",
        font={"color": "#d1d5db", "size": 11},
        xaxis={"side": "top", "showgrid": False, "zeroline": False, "fixedrange": True},
        yaxis={"showgrid": False, "zeroline": False, "fixedrange": True, "autorange": "reversed"},
    )
    fig.update_traces(textfont={"size": 11, "color": "#e5e7eb"})
    render_section_label(
        "Structural Coupling Map",
        "Pairwise proxy movement is resolved into threshold bands; correlation remains the raw input, not the diagnosis.",
    )
    render_coupling_legend()
    st.plotly_chart(fig, use_container_width=True)


def _selection_points(selection_obj: Any) -> list[dict[str, Any]]:
    if selection_obj is None:
        return []
    if isinstance(selection_obj, dict):
        return cast(list[dict[str, Any]], selection_obj.get("selection", {}).get("points", []))
    selection = getattr(selection_obj, "selection", None)
    if selection is None:
        return []
    return cast(list[dict[str, Any]], getattr(selection, "points", []) or [])


def _selected_row_indexes(selection_obj: Any) -> list[int]:
    if selection_obj is None:
        return []
    if isinstance(selection_obj, dict):
        return cast(list[int], selection_obj.get("selection", {}).get("rows", []))
    selection = getattr(selection_obj, "selection", None)
    if selection is None:
        return []
    return cast(list[int], getattr(selection, "rows", []) or [])


def render_structural_history(ctx) -> None:
    snapshots = list_snapshots(ctx)
    history = history_frame(snapshots)
    if history.empty:
        st.info("No snapshot history yet.")
        return

    render_page_header("Structural Proxy History", "Recent movement in M, D, K, X with event windows")

    by_date = {snap.run_date: snap for snap in snapshots}
    selected_date = st.session_state.get("history_selected_date") or snapshots[-1].run_date
    selected_snapshot = by_date.get(selected_date, snapshots[-1])

    render_structural_summary(structural_summary(history, selected_snapshot))

    filtered = history.copy()
    start_date = filtered["date"].min().date()
    end_date = filtered["date"].max().date()
    events = ctx.event_logger.load_events(start=str(start_date), end=str(end_date))

    # Build compression ratio series from snapshot operator diagnostics
    compression_dates: list = []
    compression_vals: list = []
    for snap in snapshots:
        op_diag = snap.state.operator_diagnostics
        if op_diag is not None:
            compression_dates.append(pd.to_datetime(snap.run_date))
            compression_vals.append(op_diag.compression_ratio)

    # Build event info with family colors from operator diagnostics of nearest snapshot
    event_family_map: dict = {}
    if not events.empty and snapshots:
        snap_by_date = {snap.run_date: snap for snap in snapshots}
        snap_dates = sorted(pd.to_datetime(snap.run_date) for snap in snapshots)
        for _, erow in events.iterrows():
            edate_str = str(erow.get("date", ""))
            try:
                edate_ts = pd.to_datetime(edate_str)
            except Exception:
                continue
            nearest = min(snap_dates, key=lambda d: abs((d - edate_ts).days))
            nearest_str = nearest.strftime("%Y-%m-%d")
            snap = snap_by_date.get(nearest_str)
            family = "unknown"
            if snap and snap.state.operator_diagnostics:
                apps = snap.state.operator_diagnostics.applications
                if apps:
                    family = apps[0].family
            event_family_map[edate_ts] = family

    n_rows = 6 if compression_dates else 5
    row_heights = [0.8, 1, 1, 1, 1, 0.7] if n_rows == 6 else [0.8, 1, 1, 1, 1]

    main_col, side_col = st.columns([68, 32], gap="large")
    with main_col:
        render_section_label("Time Surface", "The selected sidebar window controls all replay charts and event markers.")
        current_row = latest_filtered_row(filtered, history)
        fig = make_subplots(
            rows=n_rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=row_heights,
        )
        fig.add_trace(
            go.Scatter(
                x=filtered["date"],
                y=filtered["sigma_t"],
                mode="lines",
                fill="tozeroy",
                line={"width": 1.6, "color": "#9aa6b2"},
                fillcolor="rgba(154,166,178,0.18)",
                hovertemplate="Joint Stress<br>%{x|%Y-%m-%d}<br>%{y:.2f}<extra></extra>",
                connectgaps=True,
            ),
            row=1,
            col=1,
        )
        for event_date, family in event_family_map.items():
            vline_color = FAMILY_COLORS.get(family, "rgba(118, 130, 148, 0.48)")
            fig.add_vline(x=event_date, line_dash="dot", line_color=vline_color, line_width=1, row=1, col=1)
        for row_idx, proxy in enumerate(PROXIES, start=2):
            fig.add_trace(
                go.Scatter(
                    x=filtered["date"],
                    y=filtered[proxy],
                    mode="lines+markers",
                    line={"width": 1.7, "color": PROXY_COLORS[proxy]},
                    marker={"size": 3, "color": PROXY_COLORS[proxy], "opacity": 0.72},
                    hovertemplate=f"{proxy}<br>%{{x|%Y-%m-%d}}<br>%{{y:.2f}}<extra></extra>",
                    connectgaps=True,
                ),
                row=row_idx,
                col=1,
            )
            for event_date, family in event_family_map.items():
                vline_color = FAMILY_COLORS.get(family, "rgba(118, 130, 148, 0.48)")
                fig.add_vline(x=event_date, line_dash="dot", line_color=vline_color, line_width=1, row=row_idx, col=1)

        if compression_dates:
            fig.add_trace(
                go.Scatter(
                    x=compression_dates,
                    y=compression_vals,
                    mode="lines+markers",
                    line={"width": 1.5, "color": "#56a3a6"},
                    marker={"size": 3, "color": "#56a3a6", "opacity": 0.72},
                    hovertemplate="Compression Ratio<br>%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
                    connectgaps=True,
                ),
                row=6,
                col=1,
            )
            fig.add_hline(y=1.0, line_dash="dot", line_color="rgba(148,163,184,0.35)", line_width=1, row=6, col=1)

        fig.update_layout(
            height=820 if n_rows == 6 else 760,
            showlegend=False,
            title=None,
            margin={"t": 24, "b": 28, "l": 38, "r": 24},
            paper_bgcolor="#0e1116",
            plot_bgcolor="#0e1116",
            font={"color": "#d1d5db", "size": 11},
            hovermode="x unified",
            dragmode="pan",
        )
        fig.update_xaxes(
            showgrid=True,
            gridcolor="rgba(148,163,184,0.14)",
            zeroline=False,
            linecolor="rgba(148,163,184,0.24)",
            tickfont={"color": "#9ca3af", "size": 10},
            showspikes=True,
            spikemode="across",
            spikecolor="rgba(209,213,219,0.24)",
            spikethickness=1,
        )
        fig.update_yaxes(
            showgrid=True,
            gridcolor="rgba(148,163,184,0.14)",
            zeroline=False,
            linecolor="rgba(148,163,184,0.24)",
            tickfont={"color": "#9ca3af", "size": 10},
            nticks=4,
        )
        fig.add_annotation(
            x=0,
            y=0.995,
            xref="paper",
            yref="paper",
            showarrow=False,
            align="left",
            text="Joint Stress Surface",
            font={"size": 12, "color": "#a8b0bd"},
            xanchor="left",
        )
        for row_idx, proxy in enumerate(PROXIES, start=2):
            axis_name = "yaxis" if row_idx == 1 else f"yaxis{row_idx}"
            domain = getattr(fig.layout, axis_name).domain
            y_pos = min(float(domain[1]) + 0.018, 1.0)
            current_value = "-" if current_row is None else format_proxy_readout(current_row.get(proxy))
            fig.add_annotation(
                x=0,
                y=y_pos,
                xref="paper",
                yref="paper",
                showarrow=False,
                align="left",
                text=f"{PROXY_FULL_NAMES[proxy]} ({proxy})",
                font={"size": 12, "color": "#a8b0bd"},
                xanchor="left",
            )
            fig.add_annotation(
                x=1,
                y=y_pos,
                xref="paper",
                yref="paper",
                showarrow=False,
                align="right",
                text=f"Current {current_value}",
                font={"size": 12, "color": "#d1d5db"},
                xanchor="right",
            )
        if compression_dates:
            yaxis6 = getattr(fig.layout, "yaxis6", None)
            if yaxis6:
                domain6 = yaxis6.domain
                y6_pos = min(float(domain6[1]) + 0.018, 1.0)
                fig.add_annotation(
                    x=0, y=y6_pos, xref="paper", yref="paper",
                    showarrow=False, align="left",
                    text="Compression Ratio (DoF)",
                    font={"size": 12, "color": "#56a3a6"}, xanchor="left",
                )
        last_label_row = n_rows - 1
        for row_idx in range(1, last_label_row + 1):
            fig.update_xaxes(showticklabels=False, row=row_idx, col=1)
        fig.update_xaxes(showticklabels=True, row=n_rows, col=1)
        selected = st.plotly_chart(
            fig,
            use_container_width=True,
            key="history_plot",
            on_select="rerun",
            selection_mode="points",
            config={"displayModeBar": False, "scrollZoom": False},
        )
        render_event_note(len(event_family_map))
        if event_family_map:
            families_seen = set(event_family_map.values())
            chips = "".join(
                f'<span style="display:inline-flex;align-items:center;gap:5px;margin:0 10px 4px 0;font-size:11px;color:#a8b0bd;">'
                f'<span style="width:9px;height:9px;background:{FAMILY_COLORS.get(f, "#a8b0bd")};border-radius:2px;"></span>{f}</span>'
                for f in sorted(families_seen)
            )
            st.markdown(f'<div style="margin:2px 0 6px 0;">{chips}</div>', unsafe_allow_html=True)
        points = _selection_points(selected)
        if points:
            picked_x = points[0].get("x")
            if picked_x is not None:
                st.session_state["history_selected_date"] = str(pd.to_datetime(picked_x).date())

    with side_col:
        selected_date = st.session_state.get("history_selected_date") or snapshots[-1].run_date
        if selected_date in by_date:
            snap = by_date[selected_date]
            render_snapshot_readout(snap, title="Interpretation")

    render_section_label("Snapshot Archive", "Stored runs remain secondary to the selected structural state.")
    archive = snapshot_archive_frame(snapshots)
    st.dataframe(archive, use_container_width=True, hide_index=True)

    render_section_label("Reflexivity Tracker", "Logged interventions are checked against T+30 and T+60 proxy movement.")
    if events.empty:
        st.info("No events logged yet.")
    else:
        tracker = build_reflexivity_tracker(events, history)
        display_cols = ["date", "actor", "intervention_type", "expected_direction", "affected_proxy", "t30_direction", "t60_direction", "reflexivity_active", "description"]
        tracker = tracker[display_cols]
        st.dataframe(tracker.style.apply(style_reflexivity_rows, axis=1), use_container_width=True, hide_index=True)
