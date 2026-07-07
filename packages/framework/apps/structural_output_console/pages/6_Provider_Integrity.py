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

from src.dynamic.renderers.markdown_renderer import render_provider_integrity

st.set_page_config(page_title="Provider integrity", layout="wide")
st.title("Provider integrity")

pip = st.session_state.get("provider_integrity")
if pip is None:
    st.info("No provider integrity JSON found for this case.")
else:
    st.markdown(render_provider_integrity(pip))
