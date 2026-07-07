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

st.set_page_config(page_title="Overview", layout="wide")
st.title("Overview")

case_id = st.session_state.get("case_id")
st.subheader(f"Active case: `{case_id}`")

c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Signal cards", len(st.session_state.get("signal_cards", [])))
with c2:
    mm = st.session_state.get("mismatch_map")
    st.metric("Mismatch profiles", len(mm.profiles) if mm else 0)
with c3:
    pip = st.session_state.get("provider_integrity")
    st.metric("Provider checks", len(pip.checks) if pip else 0)

tf = st.session_state.get("temporal_frame")
if tf:
    st.success(f"Temporal frame loaded: **{tf.case_id}** with {len(tf.phases)} phases.")
else:
    st.warning("No temporal frame embedded in the signal bundle JSON for this case.")
