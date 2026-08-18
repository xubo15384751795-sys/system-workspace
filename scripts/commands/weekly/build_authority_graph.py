#!/usr/bin/env python3
"""Build authority graph from pipeline topology.

Derives nodes and edges from daily_pipeline_registry.yaml. The default mode
writes ``Output/system_learning/latest/authority_graph.json``; ``--no-write``
provides a read-only audit mode.

Usage:
    python scripts/commands/weekly/build_authority_graph.py
    python scripts/commands/weekly/build_authority_graph.py --json
    python scripts/commands/weekly/build_authority_graph.py --json --no-write
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys

from scripts._runtime_io import ROOT


def _load_authority_graph_module():
    path = ROOT / "scripts" / "_authority_graph.py"
    spec = importlib.util.spec_from_file_location("_authority_graph", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load authority graph module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_AUTHORITY_GRAPH = _load_authority_graph_module()
build_authority_graph = _AUTHORITY_GRAPH.build_authority_graph
write_authority_graph = _AUTHORITY_GRAPH.write_authority_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Build authority graph from pipeline topology.")
    parser.add_argument("--json", action="store_true", help="Print graph JSON to stdout.")
    parser.add_argument(
        "--fail-on-invariant",
        action="store_true",
        help="Exit non-zero when high-severity graph invariants fail.",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Build and validate the graph without writing an Output artifact.",
    )
    args = parser.parse_args()

    graph = build_authority_graph(ROOT)
    output_path = None if args.no_write else write_authority_graph(graph, ROOT)

    if args.json:
        print(json.dumps(graph, indent=2, ensure_ascii=False))
    else:
        metrics = graph.get("metrics", {})
        invariants = graph.get("invariants", {})
        if output_path is None:
            print("Authority graph: not written (--no-write)")
        else:
            print(f"Authority graph: {output_path.relative_to(ROOT)}")
        print(f"Pipeline steps: {metrics.get('pipeline_step_count')}")
        print(f"Core-capable steps: {metrics.get('core_capable_step_count')}")
        print(f"Declared/derived drift: {metrics.get('drift_count')}")
        print(f"Invariants valid: {invariants.get('valid')}")
        violations = invariants.get("violations", [])
        high = [v for v in violations if v.get("severity") == "high"]
        if high:
            for item in high[:5]:
                print(f"  [high] {item.get('message')}")

    if args.fail_on_invariant and not graph.get("invariants", {}).get("valid", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
