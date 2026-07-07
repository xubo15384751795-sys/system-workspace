from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src.ui.components.paper_dashboard import render_page_header


def render(ctx) -> None:
    render_page_header(
        "Surveillance",
        "Dual-Track View",
        "Daily FastSignal surveillance beside the latest weekly canonical structural readout.",
    )
    fast = _load_payloads(ctx.snapshot_store, "fast_signals", "date")
    validations = _load_payloads(ctx.snapshot_store, "cross_validations", "date")

    if fast.empty:
        st.info("No fast signals have been generated yet.")
        return

    latest_fast = fast.iloc[-1]
    latest_validation = validations.iloc[-1] if not validations.empty else None
    cols = st.columns(4)
    cols[0].metric("Fast Date", str(latest_fast.get("date", "")))
    cols[1].metric("Alert", str(latest_fast.get("alert_level", "CLEAR")))
    cols[2].metric("Composite", _fmt(latest_fast.get("composite")))
    cols[3].metric(
        "Cross Verdict",
        str(latest_validation.get("verdict", "n/a")) if latest_validation is not None else "n/a",
    )

    st.markdown("#### Fast Channels")
    channel_frame = fast[["date", "M_zscore", "D_zscore", "K_zscore", "X_zscore", "composite"]].copy()
    channel_frame["date"] = pd.to_datetime(channel_frame["date"], errors="coerce")
    st.line_chart(channel_frame.set_index("date"))

    st.markdown("#### Latest Direction Check")
    if latest_validation is None:
        st.caption("No cross-validation record available.")
    else:
        rows = []
        canonical = latest_validation.get("canonical_directions", {}) or {}
        fast_dirs = latest_validation.get("fast_directions", {}) or {}
        agreement = latest_validation.get("agreement_per_channel", {}) or {}
        for channel in ("M", "D", "K", "X"):
            rows.append(
                {
                    "channel": channel,
                    "fast": fast_dirs.get(channel, "UNKNOWN"),
                    "canonical": canonical.get(channel, "UNKNOWN"),
                    "agreement": bool(agreement.get(channel, False)),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("#### FastSignal Archive")
    display = fast.tail(30).copy()
    display["threshold_hits"] = display["threshold_hits"].apply(lambda value: ",".join(value) if isinstance(value, list) else "")
    st.dataframe(
        display[["date", "alert_level", "composite", "threshold_hits", "M_zscore", "D_zscore", "K_zscore", "X_zscore"]],
        use_container_width=True,
        hide_index=True,
    )


def _load_payloads(store, table: str, order_col: str) -> pd.DataFrame:
    try:
        rows = store.conn.execute(f"SELECT payload_json FROM {table} ORDER BY {order_col}").fetchall()
    except Exception:
        return pd.DataFrame()
    records = []
    for (payload_json,) in rows:
        try:
            records.append(json.loads(str(payload_json)))
        except json.JSONDecodeError:
            continue
    return pd.DataFrame.from_records(records)


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.2f}"
