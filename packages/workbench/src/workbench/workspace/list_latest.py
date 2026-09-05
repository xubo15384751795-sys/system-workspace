#!/usr/bin/env python3
"""Print the resolved latest paths for each subsystem.

Latest pointers in this workspace are symlinks; agents that run `find` or
`ls` over them without `-L` see an empty directory and silently skip the
release. This script always resolves through the symlink and prints a flat,
greppable summary.
"""
from __future__ import annotations

from pathlib import Path

from ._paths import (
    ARCHIVE_RUNS,
    HARVESTER_LATEST,
    NEUTRAL_PRESSURE_SNAPSHOT,
    SANDBOX_OPENBB_RUNS,
    SANDBOX_QLIB_RUNS,
)


def _resolve(p: Path) -> Path | None:
    if not p.exists():
        return None
    return p.resolve()


def _latest_run_in(runs_dir: Path) -> Path | None:
    if not runs_dir.exists():
        return None
    candidates = sorted(
        (c for c in runs_dir.iterdir() if c.is_dir() and not c.name.startswith(".")),
        key=lambda c: c.name,
    )
    return candidates[-1] if candidates else None


def main() -> int:
    """CLI entry point — print resolved latest paths for each subsystem."""
    rows: list[tuple[str, str]] = []

    h_latest = _resolve(HARVESTER_LATEST)
    rows.append(("harvester_release", str(h_latest) if h_latest else "<missing>"))

    n_latest = _resolve(NEUTRAL_PRESSURE_SNAPSHOT)
    rows.append(("neutral_pressure", str(n_latest) if n_latest else "<missing>"))

    archive_latest = _latest_run_in(ARCHIVE_RUNS)
    rows.append(("archive_runs", str(archive_latest) if archive_latest else "<none>"))

    o_latest = _latest_run_in(SANDBOX_OPENBB_RUNS)
    rows.append(("sandbox_openbb_run", str(o_latest) if o_latest else "<none>"))

    q_latest = _latest_run_in(SANDBOX_QLIB_RUNS)
    rows.append(("sandbox_qlib_run", str(q_latest) if q_latest else "<none>"))

    width = max(len(r[0]) for r in rows)
    for name, path in rows:
        print(f"{name.ljust(width)}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
