from __future__ import annotations

import pandas as pd
import streamlit as st

from src.research.scenario_path_generator import ScenarioPathGenerator
from src.ui.components.paper_dashboard import render_page_header, render_scenario_lab


def render(ctx) -> None:
    render_page_header(
        "Page 4",
        "Scenario Lab",
        "A mechanistic sandbox for leverage shocks, funding stress, collateral squeezes, run dynamics, and policy intervention.",
    )
    render_scenario_lab()
    st.markdown("#### Frontier Scenario Path")
    generator = ScenarioPathGenerator()
    names = [template.name for template in generator.templates()]
    selected = st.selectbox("Operator path hypothesis", names, key="frontier_scenario_path")
    result = generator.generate(selected)
    st.caption("Research mode: generated mechanism path, not validated prediction or portfolio instruction.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "maturity": result.maturity.value,
                    "operator_sequence": " -> ".join(result.operator_sequence),
                    "first_channel_break_candidate": result.which_channel_breaks_first or "-",
                    "observability": result.observability_classification,
                    "tradable_hypothesis_candidate": result.tradable_hypothesis_candidate,
                }
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.line_chart(pd.DataFrame([dict(row) for row in result.trajectory]))
