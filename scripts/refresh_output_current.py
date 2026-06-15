from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

# DEPRECATED: canonical path is scripts/bridge_replay_to_current.py.
# Deprecation warning is emitted by workbench.current.main().
from workbench.current import main


if __name__ == "__main__":
    raise SystemExit(main())
