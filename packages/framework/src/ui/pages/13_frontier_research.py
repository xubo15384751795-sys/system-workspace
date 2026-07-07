from __future__ import annotations

import pandas as pd
import streamlit as st

from src.research import (
    FrontierResearchEngine,
    ResearchHypothesisRegistry,
    ScenarioPathGenerator,
)
from src.ui.components.paper_dashboard import render_page_header


def render(ctx) -> None:
    render_page_header(
        "Frontier Research Engine",
        "Generate first, constrain after",
        "Variables, local state spaces, mechanisms, and candidate signals are allowed to be non-standard. Maturity tags and validation gates sit after generation.",
    )
    st.caption("变量生成权不交给风控；结论释放权不交给想象力。")
    bundle = FrontierResearchEngine().generate()
    mechanisms = bundle.mechanisms
    hypotheses = ResearchHypothesisRegistry().all()
    queue_items = bundle.validation_queue

    cols = st.columns(5)
    cols[0].metric("Local spaces", str(len(bundle.local_state_spaces)))
    cols[1].metric("Generated variables", str(len(bundle.variables)))
    cols[2].metric("Mechanisms", str(len(bundle.mechanisms)))
    cols[3].metric("Compositions", str(len(bundle.compositions)))
    cols[4].metric("Candidate signals", str(len(bundle.candidate_signals)))

    st.markdown("#### Local Structure Maps")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "state_space": item.name,
                    "maturity": item.maturity.value,
                    "thesis": item.thesis,
                    "public_proxy_families": ", ".join(item.public_proxy_families),
                    "release_boundary": item.release_boundary,
                }
                for item in bundle.local_state_spaces
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Generated Frontier Variables")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "variable": item.name,
                    "state_space": item.local_state_space,
                    "channel": item.channel,
                    "construction": item.construction,
                    "maturity": item.maturity.value,
                    "expected_horizon": item.expected_horizon,
                    "post_generation_constraints": "; ".join(item.post_generation_constraints),
                }
                for item in bundle.variables
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Structural Mechanism Library")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "mechanism": item.name,
                    "state_space": item.local_state_space,
                    "maturity": item.maturity.value,
                    "operators": " -> ".join(item.operator_names),
                    "claim_boundary": item.output_claim_boundary,
                }
                for item in mechanisms
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Mechanism Compositions")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "composition": item.name,
                    "state_space": item.local_state_space,
                    "maturity": item.maturity.value,
                    "operators": " -> ".join(item.operator_sequence),
                    "generated_variables": ", ".join(item.generated_variable_names),
                    "research_thesis": item.research_thesis,
                    "post_generation_constraints": "; ".join(item.post_generation_constraints),
                }
                for item in bundle.compositions
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Research Hypotheses")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "name": item.name,
                    "maturity": item.maturity.value,
                    "expected_horizon": item.expected_horizon,
                    "target_to_test": item.target_to_test,
                    "failure_condition": item.failure_condition,
                }
                for item in hypotheses
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Scenario Path Generator")
    generator = ScenarioPathGenerator()
    selected = st.selectbox("Scenario path", [template.name for template in generator.templates()])
    result = generator.generate(selected)
    cols = st.columns(4)
    cols[0].metric("Maturity", result.maturity.value)
    cols[1].metric("First break candidate", result.which_channel_breaks_first or "-")
    cols[2].metric("Observability", result.observability_classification)
    cols[3].metric("Operators", str(len(result.operator_sequence)))
    st.dataframe(pd.DataFrame([dict(row) for row in result.trajectory]), use_container_width=True, hide_index=True)
    st.caption(result.tradable_hypothesis_candidate)

    st.markdown("#### Validation Queue And Release Controls")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "candidate": item.candidate_name,
                    "maturity": item.maturity.value,
                    "target": item.target_to_test,
                    "tests": ", ".join(item.tests),
                    "status": item.status,
                }
                for item in queue_items
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption("Release constraints: " + " | ".join(bundle.release_constraints))
