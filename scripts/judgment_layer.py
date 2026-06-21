#!/usr/bin/env python3
"""Judgment Layer — thin wrapper.

See Workbench/src/workbench/judgment/layer.py for core logic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _workspace_imports import add_workbench_src
add_workbench_src()

from workbench.judgment.layer import (
    build_judgment, write_outputs, load_json,
    load_caselab, load_hmm, load_k_gate, load_x_gate, load_validation,
    _date_from_framework, FW_PATH,
)
from pending_evaluation import write_pending_evaluation
from paper_freshness import check_paper_world_model_freshness, lower_claim_ceiling_for_stale


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a daily bounded judgment card.")
    parser.add_argument("--date", default=None, help="Override date for CaseLab lookup.")
    parser.add_argument("--json", action="store_true", help="Print JSON to stdout after writing files.")
    args = parser.parse_args()

    fw = load_json(FW_PATH)
    if not fw:
        raise SystemExit(f"framework_output.json not found at {FW_PATH}")

    date_str = args.date or _date_from_framework(fw)
    caselab = load_caselab(date_str)
    hmm = load_hmm()
    k_gate = load_k_gate()
    x_gate = load_x_gate()
    validation = load_validation()

    card = build_judgment(fw, caselab, hmm, k_gate, x_gate, validation)

    freshness = check_paper_world_model_freshness()
    if freshness.get("stale"):
        original = card.get("claim_ceiling", "unknown")
        card["claim_ceiling"] = lower_claim_ceiling_for_stale(str(original))
        card.setdefault("confidence", {}).setdefault("reasons", []).append(
            f"Paper world model stale ({freshness.get('reason')}, "
            f"age={freshness.get('age_hours')}h) — claim ceiling lowered"
        )
        card["paper_world_model_freshness"] = freshness

    paths = write_outputs(card)
    eval_path = write_pending_evaluation("judgment_layer", card)
    if args.json:
        print(json.dumps(card, indent=2, ensure_ascii=False))
    else:
        print(f"Judgment card: {paths['markdown']}")
        print(f"Decision: {card['decision']}")
        print(f"Confidence: {card['confidence']['level']}")
        print(f"Gate status: {card['gate_status']}")


if __name__ == "__main__":
    main()
