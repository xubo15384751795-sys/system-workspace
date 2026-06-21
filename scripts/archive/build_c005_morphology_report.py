# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED LOCATION (marked 2026-05-22) — migration tracked in
#   governance/repo_layout_map.md §6
#   governance/repo_state_audit.md Phase 3
# This script should eventually live in:
#   deformation-framework/scripts/
# Path here is preserved as a thin entry point so `sys`, Justfile, tests, and
# configs continue to work. New code should target the module-owned location
# once the owning submodule absorbs this script.
# ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.c005_morphology_report import main


if __name__ == "__main__":
    raise SystemExit(main())
