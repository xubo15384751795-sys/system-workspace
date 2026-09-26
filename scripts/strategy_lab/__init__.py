"""Compatibility package for scripts.strategy_lab.* shims.

When tests put ``scripts/`` on ``sys.path``, this package would otherwise
shadow ``packages/workbench/src/strategy_lab``. Append the canonical tree so
modules that only exist there remain importable as ``strategy_lab.*``.
"""
from pathlib import Path

_CANON = Path(__file__).resolve().parents[2] / "packages" / "workbench" / "src" / "strategy_lab"
_canon = str(_CANON)
if _canon not in __path__:
    __path__.append(_canon)
