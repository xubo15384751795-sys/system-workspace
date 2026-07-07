from __future__ import annotations

import pandas as pd
import streamlit as st

from src.ui.components.paper_dashboard import (
    render_history_panels,
    render_mean_field_gap,
    render_page_header,
    render_shadow_heatmap,
    render_stress_panel,
)
from src.ui.helpers.ui_runtime import history_frame, list_snapshots


def render(ctx) -> None:
    render_page_header(
        "Page 2",
        "Structural History",
        "Small-multiple time surfaces for M, D, K, X, joint stress, shadow maturity, and mean-field gap.",
    )
    snapshots = list_snapshots(ctx)
    history = history_frame(snapshots)
    if history.empty:
        st.info("No snapshot history yet.")
        return

    c1, c2 = st.columns([1, 1])
    with c1:
        window = st.selectbox("Display window", ["Selected sidebar window", "Latest 30", "Latest 90", "All loaded"], index=0)
    with c2:
        compare = st.selectbox("Comparison marker", ["None", "March 2020", "March 2023 SVB"], index=0)

    filtered = _filter_window(history, window)
    if compare != "None":
        marker = "2020-03-12" if compare == "March 2020" else "2023-03-10"
        st.caption(f"Comparison marker: {marker}")
        _render_comparison(history, marker)

    render_history_panels(filtered)
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("#### Joint Stress")
        render_stress_panel(filtered)
    with right:
        st.markdown("#### Mean-Field Gap")
        render_mean_field_gap(filtered)
    st.markdown("#### Shadow Maturity Heatmap")
    render_shadow_heatmap(filtered)


def _filter_window(history: pd.DataFrame, window: str) -> pd.DataFrame:
    if window == "Latest 30":
        return history.tail(30)
    if window == "Latest 90":
        return history.tail(90)
    return history


def _render_comparison(history: pd.DataFrame, marker: str) -> None:
    target = pd.to_datetime(marker)
    base_idx = (history["date"] - target).abs().idxmin()
    base = history.loc[base_idx]
    current = history.iloc[-1]
    cols = st.columns(5)
    cols[0].metric("Comparison date", pd.to_datetime(base["date"]).strftime("%Y-%m-%d"))
    for col, channel in zip(cols[1:], ["M", "D", "K", "X"]):
        delta = float(current.get(channel, 0.0) or 0.0) - float(base.get(channel, 0.0) or 0.0)
        col.metric(f"Delta {channel}", f"{delta:+.2f}")
