from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def hub_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_hub_project_root(system_root: Path) -> Path:
    named = system_root / "System Learning Hub"
    if named.is_dir():
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
        system_root: Path,
        *,
        ledger_dir: Path | None = None,
        report_dir: Path | None = None,
    ) -> HubPaths:
        root = system_root.expanduser().resolve()
        return cls(
            system_root=root,
            ledger_dir=(ledger_dir or root / "Data" / "system_learning" / "ledgers").resolve(),
            report_dir=(report_dir or root / "Output" / "system_learning" / "latest").resolve(),
            runs_dir=(root / "Data" / "system_learning" / "runs").resolve(),
            events_dir=(root / "Output" / "system_learning" / "events").resolve(),
            runtime_log_dir=(root / "Output" / "system_learning" / "runtime").resolve(),
            hub_project_root=resolve_hub_project_root(root),
        )
