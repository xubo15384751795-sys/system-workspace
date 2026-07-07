from __future__ import annotations

import streamlit as st

from src.ui.components.paper_dashboard import CASE_LIBRARY, render_case_replay, render_page_header


def render(ctx) -> None:
    render_page_header(
        "Page 3",
        "Case Replay",
        "Historical stress episodes replayed as structural mechanism chains rather than narrative anecdotes.",
    )
    case_name = st.sidebar.selectbox("Historical case", list(CASE_LIBRARY.keys()), key="case_replay_name")
    render_case_replay(case_name)
