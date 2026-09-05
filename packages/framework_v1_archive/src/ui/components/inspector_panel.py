from __future__ import annotations

import streamlit as st

from src.interpretation.market_state import PATTERN_COLORS, interpret_snapshot
from src.operators.operator_schema import OperatorDiagnostics


def _render_operator_section(op_diag: OperatorDiagnostics | None) -> None:
    st.markdown("### Operator Sequence")
    if op_diag is None or op_diag.operator_count == 0:
        st.caption("No operators applied in current window.")
        return

    proximity_pct = min(100, int(op_diag.singular_proximity * 100))
    prox_color = "#7aa879" if proximity_pct < 40 else "#d99a52" if proximity_pct < 75 else "#d66a5f"
    st.markdown(
        (
            f'<div style="display:flex;gap:16px;margin:4px 0 10px 0;font-size:12px;color:#9aa6b2;">'
            f'<span>Ops: <strong style="color:#e5e7eb;">{op_diag.operator_count}</strong></span>'
            f'<span>Proximity: <strong style="color:{prox_color};">{proximity_pct}%</strong></span>'
            f'<span>Non-comm: <strong style="color:#9aa6b2;">{op_diag.non_commutativity_score:.3f}</strong></span>'
            f'<span>Compression: <strong style="color:#56a3a6;">{op_diag.compression_ratio:.3f}</strong></span>'
            f'</div>'
        ),
        unsafe_allow_html=True,
    )
    if op_diag.sequence_signature:
        st.caption(f"Sequence: {op_diag.sequence_signature}")

    if op_diag.applications:
        import pandas as pd

        rows = []
        for app in op_diag.applications:
            rows.append({
                "Operator": app.operator_name,
                "Family": app.family,
                "ΔM": f"{app.delta.get('M', 0):+.4f}",
                "ΔD": f"{app.delta.get('D', 0):+.4f}",
                "ΔK": f"{app.delta.get('K', 0):+.4f}",
                "ΔX": f"{app.delta.get('X', 0):+.4f}",
                "Date": app.event_date or "-",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def narrative_badge(value: str | None) -> str:
    normalized = (value or "UNKNOWN").upper()
    if normalized == "ANCHORED":
        color = "#2f855a"
    elif normalized == "DRIFTING":
        color = "#d69e2e"
    elif normalized == "COMPRESSION_ILLUSION":
        color = "#c53030"
    else:
        color = "#718096"
    return (
        f'<span style="background:{color};color:white;padding:4px 10px;'
        'border-radius:999px;font-size:12px;font-weight:600;">'
        f"{normalized}</span>"
    )


def render_inspector_panel(snapshot) -> None:
    interpretation = interpret_snapshot(snapshot)
    if snapshot.escalation:
        st.error("Human judgment required — automated diagnosis suspended")
        st.markdown(f"**Escalation Reason:** {snapshot.escalation_reason or '-'}")
    else:
        pattern = interpretation.pattern
        color = PATTERN_COLORS.get(pattern, "#4a5568")
        st.markdown("### Current Pattern")
        st.markdown(
            f'<div style="display:inline-block;font-size:26px;font-weight:760;color:{color};'
            'margin:8px 0 10px 0;white-space:nowrap;letter-spacing:-.01em;">'
            f'{pattern}</div>',
            unsafe_allow_html=True,
        )
        st.caption(interpretation.summary)

        st.markdown("### Narrative Drift Status")
        narrative = snapshot.narrative
        ai = narrative.ai_unicorn if narrative else None
        clo = narrative.clo_cmbs if narrative else None
        policy = narrative.policy if narrative else None
        st.markdown(
            (
                "<div style='display:grid;gap:10px'>"
                f"<div><strong>AI Unicorn:</strong> {narrative_badge(ai)}</div>"
                f"<div><strong>CLO/CMBS:</strong> {narrative_badge(clo)}</div>"
                f"<div><strong>Policy:</strong> {narrative_badge(policy)}</div>"
                "</div>"
            ),
            unsafe_allow_html=True,
        )

    st.markdown("### Recommended Next Actions")
    for idx, action in enumerate(interpretation.recommended_actions, start=1):
        st.markdown(f"{idx}. {action}")

    _render_operator_section(snapshot.state.operator_diagnostics)
