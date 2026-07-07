from __future__ import annotations

import pandas as pd
import streamlit as st

from src.core.feature_taxonomy import FeatureLayer, tags_for_layer
from src.ui.components.paper_dashboard import render_operator_sequence, render_page_header
from src.ui.components.research_log_panel import render_graph_explorer
from src.ui.helpers.ui_runtime import get_shared_snapshot, snapshot_json


def render(ctx, task: str) -> None:
    render_page_header(
        "Exploratory Lab",
        task,
        "Experimental extensions beyond the current paper claim. Useful for research discovery, not for SRC/UCL main-flow evidence.",
    )
    st.dataframe(
        pd.DataFrame([tag.__dict__ | {"layer": tag.layer.value} for tag in tags_for_layer(FeatureLayer.EXPLORATORY)]),
        use_container_width=True,
        hide_index=True,
    )
    snapshot = get_shared_snapshot(ctx)
    if task == "Exploratory Graph Lab":
        render_graph_explorer(ctx)
    elif task == "Advanced Operator Diagnostics":
        render_operator_sequence(snapshot, include_exploratory=True)
    elif task == "Snapshot JSON":
        if snapshot is None:
            st.info("No snapshot available yet.")
        else:
            st.code(snapshot_json(snapshot), language="json")
    else:
        _render_ml_extensions(snapshot)


def _render_ml_extensions(snapshot) -> None:
    if snapshot is None:
        st.info("No snapshot available yet.")
        return
    extension = snapshot.extension()
    st.markdown("#### ML / Belief Extension")
    st.json(
        {
            "anomaly_score": extension.anomaly_score,
            "reflexivity_flags": dict(extension.reflexivity_flags),
            "narrative": (
                {
                    "ai_unicorn": extension.narrative.ai_unicorn,
                    "clo_cmbs": extension.narrative.clo_cmbs,
                    "policy": extension.narrative.policy,
                    "drift_scores": dict(extension.narrative.drift_scores),
                }
                if extension.narrative is not None
                else None
            ),
            "belief_state": extension.belief_state.to_dict() if extension.belief_state is not None else None,
        }
    )
