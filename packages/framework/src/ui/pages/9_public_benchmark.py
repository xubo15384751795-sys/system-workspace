from __future__ import annotations

import pandas as pd
import streamlit as st

from src.benchmarks.public_baselines import build_public_baselines
from src.ui.components.paper_dashboard import render_page_header


def render(ctx) -> None:
    render_page_header(
        "Public Benchmark",
        "Fair public-data baselines",
        "Compares structural signals against simple public baselines. This page is descriptive until OOS results exist.",
    )
    frame = _demo_frame()
    results = build_public_baselines(frame)
    rows = []
    for name, data in results.items():
        latest = data.iloc[-1]
        rows.append(
            {
                "baseline": name,
                "score": latest["score"],
                "percentile_score": latest["percentile_score"],
                "regime_label": latest["regime_label"],
                "confidence": latest["confidence"],
                "data_coverage": latest["data_coverage"],
                "source_features": ", ".join(latest["source_features"]),
            }
        )
    st.caption("Baseline rank is not an alpha result. It is a public-data comparison boundary.")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _demo_frame() -> pd.DataFrame:
    idx = pd.date_range("2020-01-03", periods=160, freq="W-FRI")
    return pd.DataFrame(
        {
            "VIXCLS": [18.0] * 80 + [24.0] * 40 + [20.0] * 40,
            "BAMLH0A0HYM2": [4.0] * 80 + [5.5] * 40 + [4.8] * 40,
            "NFCI": [-0.4] * 80 + [0.2] * 40 + [-0.1] * 40,
            "T10Y2Y": [0.8] * 80 + [-0.2] * 40 + [0.1] * 40,
            "STLFSI4": [-0.5] * 80 + [0.5] * 40 + [0.0] * 40,
        },
        index=idx,
    )
