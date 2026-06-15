#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED LOCATION (marked 2026-05-22) — migration tracked in
#   governance/repo_layout_map.md §6
#   governance/repo_state_audit.md Phase 3
# This script should eventually live in:
#   Workbench/ or Framework CLI (TBD)
# Path here is preserved as a thin entry point so `sys`, Justfile, tests, and
# configs continue to work. New code should target the module-owned location
# once the owning submodule absorbs this script.
# ─────────────────────────────────────────────────────────────────────────────
"""CLI for framework registry operations.

Usage:
  python3 scripts/framework_cli.py list
  python3 scripts/framework_cli.py register --id macro_regime --contract Frameworks/macro-regime/framework.yaml
  python3 scripts/framework_cli.py unregister macro_regime
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Workbench" / "src"))

from workbench.framework_registry import (
    load_registry,
    list_frameworks,
    register_framework,
    unregister_framework,
    REGISTRY_PATH,
)


def cmd_list() -> None:
    print("Registered frameworks:")
    print(list_frameworks())


def cmd_register(framework_id: str, contract_path: str) -> None:
    contract_abs = Path(contract_path).resolve()
    if not contract_abs.exists():
        print(f"Error: contract file not found: {contract_abs}", file=sys.stderr)
        sys.exit(1)

    registry = register_framework(framework_id, contract_path)
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"Registered framework '{framework_id}' with contract: {contract_path}")
    print(f"Registry updated: {REGISTRY_PATH}")
    print()
    print("Run './sys refresh' to rebuild the current card.")


def cmd_unregister(framework_id: str) -> None:
    registry = load_registry()
    existing = [fw for fw in registry.get("frameworks", []) if fw["framework_id"] == framework_id]
    if not existing:
        print(f"Framework '{framework_id}' is not registered.", file=sys.stderr)
        sys.exit(1)

    registry = unregister_framework(framework_id)
    REGISTRY_PATH.write_text(
        json.dumps(registry, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"Unregistered framework '{framework_id}'.")
    print(f"Registry updated: {REGISTRY_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Workbench Framework Registry CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all registered frameworks")

    reg = sub.add_parser("register", help="Register a new framework")
    reg.add_argument("--id", required=True, dest="framework_id", help="Framework identifier")
    reg.add_argument("--contract", required=True, dest="contract_path", help="Path to framework.yaml")

    unreg = sub.add_parser("unregister", help="Unregister a framework")
    unreg.add_argument("framework_id", help="Framework identifier to remove")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list()
    elif args.command == "register":
        cmd_register(args.framework_id, args.contract_path)
    elif args.command == "unregister":
        cmd_unregister(args.framework_id)


if __name__ == "__main__":
    main()
