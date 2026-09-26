from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


def default_system_root() -> Path:
    """Return the application-injected workspace root."""
    from system_runtime.context import RuntimeContext

    return RuntimeContext.current_context().workspace


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
    # A standalone Hub caller must provide a valid application workspace. Do
    # not infer a repository parent from the installed package location.
    return canonical


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
