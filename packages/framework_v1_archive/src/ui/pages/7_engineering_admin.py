from __future__ import annotations

import pandas as pd
import streamlit as st

from src.core.feature_taxonomy import FeatureLayer, tags_for_layer
from src.ui.components.paper_dashboard import render_page_header
from src.ui.helpers.ui_runtime import get_shared_snapshot


def render(ctx) -> None:
    render_page_header(
        "Engineering Dashboard",
        "Runtime & Cache",
        "Implementation-required controls and diagnostics. These are not main research claims.",
    )
    st.markdown("#### Engineering Feature Tags")
    st.dataframe(
        pd.DataFrame([tag.__dict__ | {"layer": tag.layer.value} for tag in tags_for_layer(FeatureLayer.ENGINEERING)]),
        use_container_width=True,
        hide_index=True,
    )
    snapshot = get_shared_snapshot(ctx)
    if snapshot is not None:
        st.markdown("#### Evidence Escalation")
        st.write(
            {
                "escalation": snapshot.escalation,
                "escalation_reason": snapshot.escalation_reason,
                "data_quality": dict(snapshot.state.provenance.get("data_quality", {}) or {}),
            }
        )
    st.markdown("#### Runtime Configuration")
    st.json(
        {
            "data_sources": ctx.config.get("data_sources", {}),
            "pipeline": ctx.config.get("pipeline", {}),
            "thresholds": ctx.config.get("thresholds", {}),
            "output": ctx.config.get("output", {}),
        }
    )
    data_hub = getattr(ctx.pipeline, "data_hub", None)
    if data_hub is None:
        data_hub = getattr(ctx.pipeline.data_source, "_hub", None)
    if data_hub is not None and hasattr(data_hub, "provider_capabilities"):
        st.markdown("#### Provider Capability Registry")
        st.dataframe(pd.DataFrame(data_hub.provider_capabilities()), use_container_width=True, hide_index=True)
