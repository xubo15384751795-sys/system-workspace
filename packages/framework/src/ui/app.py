"""Legacy interactive UI retained for compatibility.

No new features should be added here. New UI work should target
src.ui.run_viewer, which renders finalized run packages without fetching data
or invoking computation modules.
"""

from __future__ import annotations

import importlib

import streamlit as st

from src.core.runtime_context import RuntimePaths
from src.ui.components.paper_dashboard import inject_academic_css
from src.ui.helpers.ui_runtime import get_context, render_runtime_status, render_workspace_controls


st.set_page_config(page_title="Structural Deformation Research System", page_icon="SDRS", layout="wide")
inject_academic_css()
st.markdown(
    """
    <div style="border-bottom:1px solid #d9dee8;margin-bottom:12px;padding-bottom:8px;">
      <div style="font-size:13px;color:#667085;text-transform:uppercase;font-weight:700;">
        Structural Deformation Research System
      </div>
      <div style="font-size:12px;color:#667085;margin-top:2px;">
        Paper-facing structural state dashboard · reproducible research interface
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

ctx = get_context()
task = render_workspace_controls(ctx, key_prefix="app")
dashboard_mode = st.session_state.get("_dashboard_mode", "Paper Dashboard")
if dashboard_mode == "Engineering Dashboard":
    render_runtime_status(ctx)

if task == "Current Structural State":
    importlib.import_module("src.ui.pages.1_current_state").render(ctx)
elif task == "Structural History":
    importlib.import_module("src.ui.pages.4_structural_history").render(ctx)
elif task == "Case Replay":
    importlib.import_module("src.ui.pages.3_case_replay").render(ctx)
elif task == "Scenario Lab":
    importlib.import_module("src.ui.pages.3_scenario_lab").render(ctx)
elif task == "Operator Sequence":
    importlib.import_module("src.ui.pages.5_operator_sequence").render(ctx)
elif task == "Public Benchmark":
    importlib.import_module("src.ui.pages.9_public_benchmark").render(ctx)
elif task == "Signal Decomposition":
    importlib.import_module("src.ui.pages.10_signal_decomposition").render(ctx)
elif task == "Dual-Track Surveillance":
    importlib.import_module("src.ui.pages.14_dual_track_surveillance").render(ctx)
elif task == "Frontier Research Engine":
    importlib.import_module("src.ui.pages.13_frontier_research").render(ctx)
elif task == "Claim Guard / Evidence Boundary":
    importlib.import_module("src.ui.pages.11_claim_guard").render(ctx)
elif task == "Evidence & Provenance":
    importlib.import_module("src.ui.pages.6_evidence_provenance").render(ctx)
elif task == "Observability & Miss Taxonomy":
    importlib.import_module("src.ui.pages.12_observability").render(ctx)
elif task == "Runtime & Cache":
    importlib.import_module("src.ui.pages.7_engineering_admin").render(ctx)
else:
    importlib.import_module("src.ui.pages.8_exploratory_lab").render(ctx, task)

_default_output = str(RuntimePaths.discover().output_root)

st.caption(
    f"Data mode: {ctx.data_mode} · output dir: {ctx.config.get('output', {}).get('dir', _default_output)}"
)
