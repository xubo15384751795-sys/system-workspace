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

from src.dynamic.charts.criticality_bar import build_spec as build_crit_spec
from src.dynamic.charts.criticality_bar import render_plotly as render_crit_plotly
from src.dynamic.renderers.markdown_renderer import render_criticality

st.set_page_config(page_title="Criticality", layout="wide")
st.title("Criticality")

cs = st.session_state.get("criticality")
if cs is None:
    st.info("No criticality JSON found for this case.")
else:
    st.markdown(render_criticality(cs))
    spec = build_crit_spec(cs)
    fig = render_crit_plotly(spec)
    st.plotly_chart(fig, use_container_width=True)
