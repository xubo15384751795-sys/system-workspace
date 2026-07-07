from __future__ import annotations

import streamlit as st

from src.ui.components.research_log_panel import render_graph_explorer
from src.ui.components.snapshot_readout import render_snapshot_readout
from src.ui.helpers.ui_runtime import latest_snapshot, snapshot_json


def render(ctx) -> None:
    st.markdown(
        '<div style="font-size:12px;color:#7f8a99;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px;">'
        "Explain / Structural Context</div>",
        unsafe_allow_html=True,
    )
    snapshot = latest_snapshot(ctx)
    if snapshot is None:
        st.info("No snapshot available yet.")
        return

    render_snapshot_readout(snapshot, title="Latest Snapshot")
    render_graph_explorer(ctx)
    with st.expander("Snapshot JSON", expanded=False):
        st.code(snapshot_json(snapshot), language="json")
