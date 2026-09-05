from __future__ import annotations

import streamlit as st

from src.ui.components.paper_dashboard import (
    render_evidence_badge,
    render_metric_cards,
    render_page_header,
    render_phase_diagram,
    render_regime_callout,
    render_shadow_maturity,
    render_signature_quantities,
)
from src.ui.helpers.ui_runtime import get_shared_snapshot, history_frame, list_snapshots


def render(ctx) -> None:
    render_page_header(
        "Page 1",
        "Current Structural State",
        "A 30-second readout of the present M/D/K/X configuration, singular-region proximity, and evidence quality.",
    )
    snapshot = get_shared_snapshot(ctx)
    render_evidence_badge(snapshot)
    if snapshot is None:
        st.info("No snapshot available yet. Use Run Pipeline in the sidebar to generate the first readout.")
        return

    history = history_frame(list_snapshots(ctx))
    render_metric_cards(snapshot, history)
    st.write("")
    render_regime_callout(snapshot)

    left, right = st.columns([2, 1], gap="large")
    with left:
        st.markdown("#### D/K Phase Diagram")
        render_phase_diagram(history.tail(90), snapshot)
    with right:
        st.markdown("#### Shadow Maturity Profile")
        render_shadow_maturity(snapshot)

    st.markdown("#### Signature Quantities")
    render_signature_quantities(snapshot)
