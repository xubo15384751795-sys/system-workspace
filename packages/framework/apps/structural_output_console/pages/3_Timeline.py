from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_CONSOLE_ROOT = Path(__file__).resolve().parents[1]
if str(_CONSOLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONSOLE_ROOT))

from _paths import repo_root

_ROOT = repo_root(Path(__file__))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.dynamic.charts.timeline_chart import build_spec as build_timeline_spec
from src.dynamic.charts.timeline_chart import render_plotly as render_timeline_plotly

st.set_page_config(page_title="Timeline", layout="wide")
st.title("Timeline")

tf = st.session_state.get("temporal_frame")
if tf is None:
    st.warning("No embedded temporal frame in signal bundle JSON.")
else:
    spec = build_timeline_spec(tf)
    fig = render_timeline_plotly(spec)
    st.plotly_chart(fig, use_container_width=True)
