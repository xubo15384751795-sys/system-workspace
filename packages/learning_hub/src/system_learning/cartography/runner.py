from __future__ import annotations

import argparse
from pathlib import Path

from system_learning.cartography.report import write_cartography_outputs
from system_learning.cartography.scanner import scan_project
from system_learning.runtime.paths import resolve_hub_project_root


def run_cartography(*, scan_root: Path, project_root: Path) -> dict[str, Path]:
    scans = scan_project(scan_root)
    return write_cartography_outputs(project_root, scan_root, scans)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codebase cartography sensor (standalone).")
    parser.add_argument("--scan-root", type=Path, default=Path("/Users/a1/System"))
    parser.add_argument("--project-root", type=Path, default=None)
    args = parser.parse_args(argv)

    scan_root = args.scan_root.expanduser().resolve()
    project_root = (args.project_root or resolve_hub_project_root(scan_root)).resolve()
    outputs = run_cartography(scan_root=scan_root, project_root=project_root)

    print(f"Scanned under {scan_root} (project root {project_root}).")
    for name, path in outputs.items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
