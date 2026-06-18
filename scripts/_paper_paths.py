"""Re-export Paper path helper for scripts/ imports."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from caselab_context.paper_paths import paper_root

__all__ = ["paper_root"]
