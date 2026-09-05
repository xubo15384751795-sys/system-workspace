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

from src.dynamic.charts.mismatch_matrix import build_spec as build_mismatch_spec
from src.dynamic.charts.mismatch_matrix import render_plotly as render_mismatch_plotly
from src.dynamic.renderers.markdown_renderer import render_mismatch_map

st.set_page_config(page_title="Mismatch", layout="wide")
st.title("Mismatch map")

mm = st.session_state.get("mismatch_map")
if mm is None:
    st.info("No mismatch map JSON found for this case.")
else:
    st.markdown(render_mismatch_map(mm))
    spec = build_mismatch_spec(mm)
    fig = render_mismatch_plotly(spec)
    st.plotly_chart(fig, use_container_width=True)
