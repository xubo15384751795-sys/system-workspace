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

st.set_page_config(page_title="Research note", layout="wide")
st.title("Research note")

md = st.session_state.get("research_note_md")
if md:
    st.markdown(md)
else:
    st.info("No rendered Markdown found under `outputs/dynamic/markdown/` for this case.")
