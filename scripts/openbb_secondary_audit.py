#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED LOCATION (marked 2026-05-22) — migration tracked in
#   governance/repo_layout_map.md §6
#   governance/repo_state_audit.md Phase 3
# This script should eventually live in:
#   structural-risk-harvester/scripts/
# Path here is preserved as a thin entry point so `sys`, Justfile, tests, and
# configs continue to work. New code should target the module-owned location
# once the owning submodule absorbs this script.
# ─────────────────────────────────────────────────────────────────────────────
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Workbench" / "src"))

from workbench.openbb_secondary_audit import main

if __name__ == "__main__":
    raise SystemExit(main())
