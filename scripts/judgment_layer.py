#!/usr/bin/env python3
"""Judgment Layer — thin wrapper.

See Workbench/src/workbench/judgment/layer.py for core logic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from _workspace_imports import add_workbench_src
add_workbench_src()

from workbench.judgment.layer import (
    build_judgment, write_outputs, load_json,
    load_caselab, load_hmm, load_k_gate, load_x_gate, load_validation,
    _date_from_framework, FW_PATH,
)
from pending_evaluation import write_pending_evaluation


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
