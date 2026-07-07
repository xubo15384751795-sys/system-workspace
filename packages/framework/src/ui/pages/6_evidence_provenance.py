from __future__ import annotations

from src.ui.components.paper_dashboard import render_evidence_table, render_page_header
from src.ui.helpers.ui_runtime import get_shared_snapshot


def render(ctx) -> None:
    render_page_header(
        "Page 6",
        "Evidence & Provenance",
        "Proxy baskets, fallback status, calibration thresholds, and snapshot lineage for reproducible inspection.",
    )
    render_evidence_table(get_shared_snapshot(ctx), ctx)
