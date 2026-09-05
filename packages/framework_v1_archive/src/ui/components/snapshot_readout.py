from __future__ import annotations

from html import escape

import streamlit as st

from src.interpretation.market_state import PATTERN_COLORS, interpret_snapshot


def format_sigma(value: float | None) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def format_bool(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if bool(value) else "no"


def reflexivity_summary(flags: dict[str, bool] | None) -> str:
    items = dict(flags or {})
    if not items:
        return "Unavailable"
    active = [name for name, value in sorted(items.items()) if value]
    if not active:
        return "Quiet"
    return ", ".join(f"{name.replace('_', ' ').title()} Active" for name in active)


def snapshot_source(snapshot) -> str:
    provenance = dict(getattr(snapshot.state, "provenance", {}) or {})
    return provenance.get("source") or provenance.get("data_source") or provenance.get("pipeline") or "Pipeline snapshot"


def snapshot_id(snapshot) -> str:
    return f"{snapshot.run_date}-{snapshot.run_type}".lower()


def render_snapshot_readout(snapshot, title: str = "Snapshot Readout") -> None:
    interpretation = interpret_snapshot(snapshot)
    color = PATTERN_COLORS.get(interpretation.pattern, "#718096")
    sigma = format_sigma(snapshot.state.sigma_t)
    reflexivity = reflexivity_summary(dict(snapshot.state.reflexivity_flags))
    regime = "Singular watch" if snapshot.state.singular_flag else "Normal"
    escalation = "Active" if snapshot.escalation else "Inactive"

    st.markdown(
        (
            '<section style="background:#0f1722;border:1px solid #273142;border-radius:8px;'
            'padding:18px 18px;color:#e5e7eb;">'
            f'<div style="font-size:12px;color:#7f8a99;text-transform:uppercase;letter-spacing:.08em;">{escape(title)}</div>'
            '<div style="margin-top:8px;font-size:12px;color:#7f8a99;">Current Pattern</div>'
            f'<div style="font-size:26px;font-weight:700;color:{color};letter-spacing:0;'
            f'white-space:nowrap;line-height:1.05;margin-top:8px;">{escape(interpretation.pattern)}</div>'
            f'<div style="font-size:13px;color:#a8b0bd;line-height:1.5;margin-top:20px;">{escape(interpretation.summary)}</div>'
            '<div style="height:1px;background:#273142;margin:20px 0;"></div>'
            '<div style="font-size:12px;color:#7f8a99;">Key Readout</div>'
            '<div style="display:grid;grid-template-columns:1fr auto;column-gap:16px;'
            'align-items:baseline;margin-top:8px;">'
            '<div style="color:#d1d5db;font-size:13px;">Joint Stress</div>'
            f'<div style="font-size:24px;font-weight:700;color:#e5e7eb;">{escape(sigma)}</div>'
            '</div>'
            '<div style="height:1px;background:#273142;margin:20px 0;"></div>'
            '<div style="font-size:12px;color:#7f8a99;">Secondary Context</div>'
            '<div style="display:grid;grid-template-columns:1fr auto;row-gap:8px;column-gap:14px;'
            'font-size:13px;align-items:baseline;margin-top:8px;">'
            '<div style="color:#7f8a99;">Leading Channel</div>'
            f'<div style="color:#d1d5db;">{escape(str(interpretation.leading_channel or "-"))}</div>'
            '<div style="color:#7f8a99;">Regime</div>'
            f'<div style="color:#d1d5db;">{escape(regime)}</div>'
            '<div style="color:#7f8a99;">Reflexivity</div>'
            f'<div style="color:#d1d5db;">{escape(reflexivity)}</div>'
            '<div style="color:#7f8a99;">Escalation</div>'
            f'<div style="color:#d1d5db;">{escape(escalation)}</div>'
            '</div>'
            '<div style="height:1px;background:#273142;margin:20px 0;"></div>'
            '<div style="font-size:12px;color:#7f8a99;">Metadata</div>'
            '<div style="display:grid;grid-template-columns:1fr auto;row-gap:8px;column-gap:14px;'
            'font-size:11px;align-items:baseline;margin-top:8px;">'
            '<div style="color:#697386;">Date</div>'
            f'<div style="color:#9ca3af;">{escape(str(snapshot.run_date))}</div>'
            '<div style="color:#697386;">Source</div>'
            f'<div style="color:#9ca3af;">{escape(snapshot_source(snapshot))}</div>'
            '<div style="color:#697386;">Snapshot ID</div>'
            f'<div style="color:#9ca3af;">{escape(snapshot_id(snapshot))}</div>'
            '</div>'
            '</section>'
        ),
        unsafe_allow_html=True,
    )

    with st.expander("Technical details", expanded=False):
        st.markdown(f"**anomaly_score:** `{snapshot.state.anomaly_score}`")
        st.markdown(f"**escalation:** `{format_bool(snapshot.escalation)}`")
        if snapshot.escalation_reason:
            st.markdown(f"**escalation_reason:** `{snapshot.escalation_reason}`")
