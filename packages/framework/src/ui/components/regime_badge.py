from __future__ import annotations

from html import escape

import streamlit as st


def sigma_color(sigma_t: float | None) -> str:
    if sigma_t is None:
        return "#a0aec0"
    value = max(0.0, min(1.0, sigma_t))
    if value < 0.3:
        return "#2f855a"
    if value < 0.6:
        return "#d69e2e"
    return "#c53030"


def render_regime_badge(sigma_t: float | None, singular_flag: bool, sigma_vector: dict | None = None) -> None:
    sigma_value = max(0.0, min(1.0, float(sigma_t or 0.0)))
    sigma_text = "-" if sigma_t is None else f"{float(sigma_t):.2f}"
    dominant = (sigma_vector or {}).get("dominant_channel") or "-"
    cofire = (sigma_vector or {}).get("cofire_count", 0)
    st.markdown("#### Joint Stress Score")
    st.markdown(
        (
            '<div style="background:#111827;border:1px solid #2a3342;border-radius:10px;padding:12px 13px;color:#e5e7eb;">'
            '<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">'
            '<span style="font-size:12px;color:#9ca3af;">Sigma</span>'
            f'<span style="font-size:22px;font-weight:650;letter-spacing:-.02em;">{sigma_text}</span>'
            '</div>'
            '<div style="height:10px;background:#273142;border-radius:999px;overflow:hidden;">'
            f'<div style="height:100%;width:{sigma_value * 100:.1f}%;background:{sigma_color(sigma_t)};"></div>'
            "</div>"
            f'<div style="margin-top:7px;font-size:11px;color:#8b95a5;">Scale-clipped bar, raw score {sigma_text}</div>'
            f'<div style="margin-top:3px;font-size:11px;color:#697386;">Dominant channel: <span style="color:#d1d5db;">{escape(str(dominant))}</span>'
            f' &middot; Cofire: <span style="color:#d1d5db;">{cofire}</span></div>'
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    st.markdown("#### Regime Flag")
    if singular_flag:
        st.markdown(
            '<span style="background:#c53030;color:white;padding:6px 12px;border-radius:999px;'
            'font-size:12px;font-weight:700;">SINGULAR REGIME</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span style="background:#718096;color:white;padding:6px 12px;border-radius:999px;'
            'font-size:12px;font-weight:700;">Normal</span>',
            unsafe_allow_html=True,
        )


def render_reflexivity_flags(flags: dict[str, bool] | None) -> None:
    st.markdown("#### Reflexivity Flags")
    items = dict(flags or {})
    if not items:
        st.caption("No reflexivity flags available.")
        return
    chips = []
    for key, active in sorted(items.items()):
        color = "#c53030" if active else "#64748b"
        label = "ACTIVE" if active else "quiet"
        chips.append(
            f'<span style="display:inline-block;background:#111827;border:1px solid {color};'
            f'color:#d1d5db;border-radius:999px;padding:4px 9px;margin:0 6px 6px 0;'
            f'font-size:11px;white-space:nowrap;">{escape(str(key))}: '
            f'<strong style="color:{color};">{label}</strong></span>'
        )
    st.markdown("".join(chips), unsafe_allow_html=True)
