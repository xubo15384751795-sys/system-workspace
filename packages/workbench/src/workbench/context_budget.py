"""Load numeric context budgets for NLP chunking and citations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from workbench.paths import workspace_root

_DEFAULTS: dict[str, Any] = {
    "chunk_window_chars": 1800,
    "excerpt_chars": 260,
    "top_k_default": 5,
    "top_k_max": 20,
}

_BUDGET_BASENAME = "context_budget.yaml"


@dataclass(frozen=True)
class ContextBudget:
    chunk_window_chars: int
    excerpt_chars: int
    top_k_default: int
    top_k_max: int

    def clamp_top_k(self, n: int) -> int:
        return max(1, min(n, self.top_k_max))


def _contracts_dir(root: Path) -> Path:
    return root / "Workbench" / "contracts" / "workbench"


def load_context_budget(*, root: Path | None = None) -> ContextBudget:
    """Load ``context_budget.yaml`` if present; otherwise use code defaults."""
    base = root or workspace_root()
    path = _contracts_dir(base) / _BUDGET_BASENAME
    data = dict(_DEFAULTS)
    if path.is_file():
        with open(path, encoding="utf-8") as f:
            merged = yaml.safe_load(f) or {}
        if isinstance(merged, dict):
            data.update({k: v for k, v in merged.items() if k in _DEFAULTS})
    return ContextBudget(
        chunk_window_chars=int(data["chunk_window_chars"]),
        excerpt_chars=int(data["excerpt_chars"]),
        top_k_default=int(data["top_k_default"]),
        top_k_max=int(data["top_k_max"]),
    )
