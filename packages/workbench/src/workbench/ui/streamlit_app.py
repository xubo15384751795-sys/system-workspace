"""Streamlit research surface for Output/current status and signal cards.

Replaces the archived research_terminal / Visualization HTML demos as the
operator-facing local UI.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import streamlit as st

from system_runtime.paths import output_surface

ROOT = Path(__file__).resolve().parents[5]
CURRENT = cast(Path, output_surface(ROOT, "current"))


def _load_json(name: str) -> dict[str, Any] | None:
    path = CURRENT / name
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return {str(key): value for key, value in payload.items()}
    except json.JSONDecodeError:
        return None


def _load_text(name: str) -> str | None:
    path = CURRENT / name
    if not path.exists():
        return None
    return str(path.read_text(encoding="utf-8"))


def main() -> None:
    st.set_page_config(page_title="Structural Risk Workbench", layout="wide")
    st.title("Structural Risk Workbench")
    st.caption(f"Reading `{CURRENT}`")

    status = _load_json("status.json")
    readme = _load_text("00_READ_ME_FIRST.md")
    signal = _load_json("signal_card.json")
    next_actions = _load_text("NEXT_ACTIONS.md")

    col1, col2, col3 = st.columns(3)
    if status:
        judgment = (status.get("judgment") or {})
        col1.metric("Decision", judgment.get("decision", "—"))
        col2.metric("Confidence", judgment.get("confidence", "—"))
        col3.metric("Claim ceiling", judgment.get("claim_ceiling", "—"))
    else:
        st.warning("status.json missing — run `./sys refresh` first.")

    tab_status, tab_signal, tab_next = st.tabs(["Status", "Signal card", "Next actions"])
    with tab_status:
        if readme:
            st.markdown(readme)
        elif status:
            st.json(status)
        else:
            st.info("No current readout.")
    with tab_signal:
        if signal:
            st.json(signal)
        else:
            signal_md = _load_text("signal_card.md")
            if signal_md:
                st.markdown(signal_md)
            else:
                st.info("No signal_card artifacts.")
    with tab_next:
        if next_actions:
            st.markdown(next_actions)
        else:
            st.info("NEXT_ACTIONS.md missing.")

    with st.expander("Raw artifacts"):
        for name in sorted(p.name for p in CURRENT.glob("*") if p.is_file()):
            st.write(name)


if __name__ == "__main__":
    main()
