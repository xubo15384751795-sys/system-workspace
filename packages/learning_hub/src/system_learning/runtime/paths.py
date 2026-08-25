from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def default_system_root() -> Path:
    """Resolve the workspace without a hardcoded machine path.

    ``SYSTEM_ROOT`` / ``SYSTEM_WORKSPACE_ROOT`` win only when they still look
    like this repository.  A stale pointer at the emptied ``/Users/a1/System``
    rename leftover is ignored so CLIs land on Verity.
    """
    from system_runtime.paths import WORKSPACE_MARKER, WorkspacePaths

    for key in ("SYSTEM_WORKSPACE_ROOT", "SYSTEM_ROOT"):
        raw = os.environ.get(key, "").strip()
        if not raw:
            continue
        root = Path(raw).expanduser().resolve()
        if (root / WORKSPACE_MARKER).is_file():
            return root
    return WorkspacePaths.discover().root


def hub_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_hub_project_root(system_root: Path) -> Path:
    canonical = system_root / "packages" / "learning_hub"
    if canonical.is_dir():
        return canonical
    named = system_root / "System Learning Hub"
    if named.is_dir():
        logger.warning(
            "Using deprecated System Learning Hub alias; "
            "migrate to packages/learning_hub"
        )
        return named
    return hub_repo_root()


@dataclass(frozen=True)
class HubPaths:
    system_root: Path
    ledger_dir: Path
    report_dir: Path
    runs_dir: Path
    events_dir: Path
    runtime_log_dir: Path
    hub_project_root: Path

    @classmethod
    def resolve(
        cls,
        system_root: Path | None = None,
        *,
        ledger_dir: Path | None = None,
        report_dir: Path | None = None,
    ) -> HubPaths:
        root = (system_root or default_system_root()).expanduser().resolve()
        return cls(
            system_root=root,
            ledger_dir=(ledger_dir or root / "Data" / "system_learning" / "ledgers").resolve(),
            report_dir=(report_dir or root / "Output" / "system_learning" / "latest").resolve(),
            runs_dir=(root / "Data" / "system_learning" / "runs").resolve(),
            events_dir=(root / "Output" / "system_learning" / "events").resolve(),
            runtime_log_dir=(root / "Output" / "system_learning" / "runtime").resolve(),
            hub_project_root=resolve_hub_project_root(root),
        )
