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

from src.dynamic.renderers.markdown_renderer import render_signal_card

st.set_page_config(page_title="Signal cards", layout="wide")
st.title("Signal cards")

cards = st.session_state.get("signal_cards", [])
if not cards:
    st.info("No signal cards JSON found for this case.")
else:
    for c in cards:
        st.markdown(render_signal_card(c))
