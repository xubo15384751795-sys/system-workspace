from __future__ import annotations

from html import escape

import streamlit as st

from src.interpretation.market_state import channel_note


PROXY_METADATA = {
    "M": {
        "name": "Mismatch",
        "subtitle": "Anchor gap",
        "label_worsening": "Anchor drift",
        "label_stable": "Contained",
        "label_improving": "Re-anchoring",
    },
    "D": {
        "name": "DoF",
        "subtitle": "Effective freedom",
        "label_worsening": "Path contraction",
        "label_stable": "Feasible",
        "label_improving": "Opening",
    },
    "K": {
        "name": "Curvature",
        "subtitle": "Transition deformation",
        "label_worsening": "Nonlinear stress",
        "label_stable": "Locally stable",
        "label_improving": "Flattening",
    },
    "X": {
        "name": "Shadow Load",
        "subtitle": "Hidden pressure",
        "label_worsening": "Accumulating",
        "label_stable": "Latent",
        "label_improving": "Releasing",
    },
}


def direction_icon(direction: str) -> tuple[str, str]:
    if direction == "WORSENING":
        return "DOWN", "#d66a5f"
    if direction == "IMPROVING":
        return "UP", "#7aa879"
    if direction == "UNKNOWN":
        return "NA", "#6b7280"
    return "FLAT", "#9ca3af"


def qualitative_label(channel: str, direction: str, available: bool) -> str:
    if not available or direction == "UNKNOWN":
        return "Missing"
    meta = PROXY_METADATA[channel]
    if direction == "WORSENING":
        return meta["label_worsening"]
    if direction == "IMPROVING":
        return meta["label_improving"]
    return meta["label_stable"]


def format_proxy_value(value: float | None, available: bool) -> str:
    if value is None or not available:
        return "unavailable"
    return f"{value:.2f}"


def render_state_cards(snapshot) -> None:
    st.subheader("Proxy State")
    st.caption("Interpretive proxy readings; values are diagnostics, not trading signals.")
    for name in ["M", "D", "K", "X"]:
        available = bool(snapshot.proxy.available.get(name, False))
        direction = str(snapshot.proxy.directions.get(name, "STABLE"))
        marker, marker_color = direction_icon(direction)
        raw_value = getattr(snapshot.proxy, name, None)
        value_text = format_proxy_value(raw_value, available)
        label = qualitative_label(name, direction, available)
        meta = PROXY_METADATA[name]
        explanation = channel_note(name, direction if available else "UNKNOWN", raw_value)
        opacity = "1.0" if available else "0.55"
        st.markdown(
            (
                '<div class="proxy-card" '
                f'style="opacity:{opacity};background:#111827;border:1px solid #2a3342;'
                'border-radius:10px;padding:13px 14px;margin-bottom:10px;'
                'box-shadow:none;color:#e5e7eb;">'
                '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">'
                '<div style="min-width:0;">'
                f'<div style="font-size:15px;font-weight:700;letter-spacing:.01em;white-space:nowrap;">{escape(meta["name"])}</div>'
                f'<div style="font-size:11px;color:#8b95a5;margin-top:1px;white-space:nowrap;">{escape(meta["subtitle"])}</div>'
                '</div>'
                f'<div style="font-size:10px;color:{marker_color};border:1px solid {marker_color};'
                'border-radius:999px;padding:2px 7px;white-space:nowrap;line-height:1.4;">'
                f'{escape(label)}</div>'
                '</div>'
                '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:10px;">'
                f'<div style="font-size:26px;font-weight:650;letter-spacing:-.02em;white-space:nowrap;">{escape(value_text)}</div>'
                f'<div style="font-size:10px;color:{marker_color};letter-spacing:.08em;">{marker}</div>'
                '</div>'
                f'<div style="font-size:12px;color:#a8b0bd;line-height:1.35;margin-top:8px;">{escape(explanation)}</div>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )
