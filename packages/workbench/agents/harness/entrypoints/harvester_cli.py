"""harvester_cli — fast-path commands for Structural Risk Harvester.

list-releases / inspect-release  use stdlib JSON + filesystem only.
fetch / run / analyze            dynamically import harvester packages.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
EXPORTS_ROOT = WORKBENCH_ROOT / "Data" / "harvester" / "exports"

HELP = """system harvester — Structural Risk Harvester commands

  list-releases [--json]           List all data releases
  inspect-release <id|latest> [--json]  Inspect a release catalog

Exit codes:  0 success  1 runtime error  2 bad arguments"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print(HELP)
        return 0

    cmd, *rest = args
    use_json = "--json" in rest
    clean = [a for a in rest if a != "--json"]

    if cmd == "list-releases":
        return _list_releases(json_output=use_json)

    if cmd == "inspect-release":
        if not clean:
            print("harvester: inspect-release requires a release id or 'latest'", file=sys.stderr)
            return 2
        return _inspect_release(clean[0], json_output=use_json)

    print(f"harvester: unknown command '{cmd}'", file=sys.stderr)
    print(HELP, file=sys.stderr)
    return 2


# ── fast-path: stdlib only ─────────────────────────────────────────────

def _resolve_release(release_id: str) -> Path | None:
    if release_id == "latest":
        latest_sym = EXPORTS_ROOT / "latest"
        if latest_sym.is_symlink():
            return latest_sym.resolve()
        return None
    candidate = EXPORTS_ROOT / release_id
    return candidate if candidate.is_dir() else None


def _release_dirs() -> list[Path]:
    if not EXPORTS_ROOT.is_dir():
        return []
    dirs: list[Path] = []
    for p in sorted(EXPORTS_ROOT.iterdir()):
        if p.is_dir() and not p.is_symlink():
            dirs.append(p)
    return dirs


def _list_releases(*, json_output: bool = False) -> int:
    releases = _release_dirs()
    if json_output:
        result = []
        for rd in releases:
            info = {"release_id": rd.name}
            catalog_path = rd / "catalog.json"
            if catalog_path.is_file():
                try:
                    cat = json.loads(catalog_path.read_text(encoding="utf-8"))
                    info["created_at"] = cat.get("created_at", "")
                    info["file_count"] = len(cat.get("files", []))
                except (OSError, json.JSONDecodeError):
                    pass
            result.append(info)
        print(json.dumps({"status": "ok", "releases": result}, indent=2))
        return 0

    if not releases:
        print("No releases found.")
        return 0
    print(f"{'RELEASE ID':<22} {'CREATED':<28} {'FILES':>6}")
    print("-" * 58)
    for rd in releases:
        created = ""
        file_count = "-"
        catalog_path = rd / "catalog.json"
        if catalog_path.is_file():
            try:
                cat = json.loads(catalog_path.read_text(encoding="utf-8"))
                created = cat.get("created_at", "")[:19]
                file_count = str(len(cat.get("files", [])))
            except (OSError, json.JSONDecodeError):
                pass
        print(f"{rd.name:<22} {created:<28} {file_count:>6}")
    return 0


def _inspect_release(release_id: str, *, json_output: bool = False) -> int:
    release_dir = _resolve_release(release_id)
    if release_dir is None:
        print(f"harvester: release not found: {release_id}", file=sys.stderr)
        return 1

    catalog_path = release_dir / "catalog.json"
    if not catalog_path.is_file():
        print(f"harvester: no catalog.json in release {release_dir.name}", file=sys.stderr)
        return 1

    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"harvester: failed to read catalog: {exc}", file=sys.stderr)
        return 1

    if json_output:
        print(json.dumps({"status": "ok", "release_id": release_dir.name, "catalog": catalog}, indent=2, default=str))
        return 0

    print(f"Release:    {release_dir.name}")
    print(f"Created:    {catalog.get('created_at', '-')}")
    print(f"Bundle:     {catalog.get('bundle_id', '-')}")
    print()
    files = catalog.get("files", [])
    if isinstance(files, list):
        print(f"Files ({len(files)}):")
        print(f"  {'PATH':<40} {'FORMAT':<10} {'ROWS':>8} {'SIZE':>10}")
        print(f"  {'-'*38}  {'-'*8}  {'-'*7}  {'-'*9}")
        for f in files:
            path = f.get("path", "-")
            fmt = f.get("format", "-")
            rows = str(f.get("row_count", "-"))
            size = _human_size(f.get("byte_size", 0))
            print(f"  {path:<40} {fmt:<10} {rows:>8} {size:>10}")
    else:
        print(f"Files:      (not a list — see raw catalog)")
    return 0


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n} {unit}"
        n //= 1024
    return f"{n} TB"


if __name__ == "__main__":
    sys.exit(main())
