from __future__ import annotations

import pandas as pd
import streamlit as st

from src.signals.signal_decomposition import count_actionable_alerts, decompose_joint_structural
from src.ui.components.paper_dashboard import render_page_header


def render(ctx) -> None:
    render_page_header(
        "Signal Decomposition",
        "Vulnerability vs transition",
        "Separates slow structural fragility from timing-research candidates. Long warnings over 120 trading days are not counted as actionable successes.",
    )
    channels = _demo_channels()
    decomposed = decompose_joint_structural(channels)
    st.line_chart(decomposed)
    alerts = count_actionable_alerts(decomposed["actionable_transition"] > 0.5, channels["event"])
    st.dataframe(pd.DataFrame([alerts]), use_container_width=True, hide_index=True)
    st.caption("Structural vulnerability is not a trading or timing signal. Transition timing remains unvalidated until rolling-origin OOS tests pass.")


def _demo_channels() -> pd.DataFrame:
    idx = pd.date_range("2022-01-03", periods=180, freq="B")
    stress = pd.Series([0.2] * 60 + [0.8] * 60 + [1.4] * 60, index=idx)
    return pd.DataFrame(
        {
            "M": stress,
            "D": -stress * 0.8,
            "K": stress.diff().abs().fillna(0.0) + stress * 0.4,
            "X": stress * 0.7,
            "event": [False] * 150 + [True] * 30,
        },
        index=idx,
    )
