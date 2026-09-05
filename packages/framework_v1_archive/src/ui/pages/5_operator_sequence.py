from __future__ import annotations

from src.ui.components.paper_dashboard import render_operator_sequence, render_page_header
from src.ui.helpers.ui_runtime import get_shared_snapshot


def render(ctx) -> None:
    render_page_header(
        "Page 5",
        "Operator Sequence",
        "Event order as structural operators, including channel response, commutator diagnostics, and a Lie-bracket proxy view.",
    )
    render_operator_sequence(get_shared_snapshot(ctx))
