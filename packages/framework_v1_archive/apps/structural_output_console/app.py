"""Streamlit shell: pick a case_id and hydrate session state from `outputs/dynamic/json`."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_CONSOLE_ROOT = Path(__file__).resolve().parent
if str(_CONSOLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONSOLE_ROOT))

from _paths import repo_root

SDRS_ROOT = repo_root(Path(__file__))
if str(SDRS_ROOT) not in sys.path:
    sys.path.insert(0, str(SDRS_ROOT))

from src.dynamic.case_pattern_registry import list_case_patterns

from payloads import (
    load_criticality,
    load_markdown_note,
    load_mismatch_map,
    load_provider_integrity,
    load_signal_bundle,
)
JSON_DIR = SDRS_ROOT / "outputs" / "dynamic" / "json"
MARKDOWN_DIR = SDRS_ROOT / "outputs" / "dynamic" / "markdown"


st.set_page_config(page_title="Structural output console", layout="wide")
st.title("Structural output console")
st.caption("Read-only viewer for `outputs/dynamic` artifacts (no Deformation Core connection).")

patterns = list_case_patterns()
default = "ldi_2022" if "ldi_2022" in patterns else patterns[0]
case_id = st.sidebar.selectbox("case_id", patterns, index=patterns.index(default) if default in patterns else 0)

if st.sidebar.button("Reload JSON", type="primary"):
    st.session_state.pop("payloads_loaded", None)

if "payloads_loaded" not in st.session_state or st.session_state.get("case_id") != case_id:
    temporal, cards = load_signal_bundle(JSON_DIR, case_id)
    st.session_state.update(
        {
            "case_id": case_id,
            "temporal_frame": temporal,
            "signal_cards": cards,
            "mismatch_map": load_mismatch_map(JSON_DIR, case_id),
            "criticality": load_criticality(JSON_DIR, case_id),
            "provider_integrity": load_provider_integrity(JSON_DIR, case_id),
            "research_note_md": load_markdown_note(MARKDOWN_DIR, case_id),
            "payloads_loaded": True,
        }
    )

st.sidebar.markdown("---")
st.sidebar.write(f"JSON dir: `{JSON_DIR}`")

missing = []
if st.session_state.get("mismatch_map") is None:
    missing.append("mismatch_map")
if st.session_state.get("criticality") is None:
    missing.append("criticality")
if missing:
    st.warning(
        "Some artifacts are missing for this case. Run `python scripts/render_ldi_output.py` from the "
        "project root to generate the LDI MVP bundle, or add matching JSON stems under `outputs/dynamic/json/`."
    )

st.info("Use the multipage sidebar entries (Overview → Research Note) to inspect each artifact.")
