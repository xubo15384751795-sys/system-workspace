"""Explicit workspace path discovery.

Runtime code must not infer the repository root with ``parents[N]``.  A caller
may inject ``SYSTEM_WORKSPACE_ROOT``; local development falls back to walking
upward for the repository marker.  Installed applications therefore work from
any current directory while tests can inject an isolated workspace.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_ENV = "SYSTEM_WORKSPACE_ROOT"
WORKSPACE_MARKER = Path("governance/daily_pipeline_registry.yaml")


def discover_workspace(start: Path | None = None) -> Path:
    override = os.environ.get(WORKSPACE_ENV)
    if override:
        root = Path(override).expanduser().resolve()
        if not (root / WORKSPACE_MARKER).is_file():
            raise RuntimeError(f"{WORKSPACE_ENV} is not a System workspace: {root}")
        return root

    candidates = [Path(start or Path.cwd()).resolve(), Path(__file__).resolve().parent]
    seen: set[Path] = set()
    for candidate in candidates:
        for directory in (candidate, *candidate.parents):
            if directory in seen:
                continue
            seen.add(directory)
            if (directory / WORKSPACE_MARKER).is_file():
                return directory
    raise RuntimeError(
        f"Cannot locate System workspace; set {WORKSPACE_ENV} to the repository root"
    )


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @classmethod
    def discover(cls, start: Path | None = None) -> "WorkspacePaths":
        return cls(discover_workspace(start))

    @property
    def governance(self) -> Path:
        return self.root / "governance"

    @property
    def output(self) -> Path:
        return self.root / "Output"

    @property
    def data(self) -> Path:
        return self.root / "Data"

    @property
    def pipeline_spec(self) -> Path:
        return self.governance / "daily_pipeline_registry.yaml"

    @property
    def current(self) -> Path:
        override = os.environ.get("CURRENT_OUTPUT_DIR")
        return Path(override).resolve() if override else self.output / "current"
