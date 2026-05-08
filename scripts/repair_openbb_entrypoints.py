#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def repair(venv: Path, *, dry_run: bool = False) -> list[Path]:
    python_path = venv / "bin" / "python"
    bin_dir = venv / "bin"
    if not python_path.exists():
        raise FileNotFoundError(f"OpenBB venv python not found: {python_path}")
    if not bin_dir.is_dir():
        raise FileNotFoundError(f"OpenBB venv bin directory not found: {bin_dir}")

    expected = f"#!{python_path}\n"
    changed: list[Path] = []
    for path in sorted(bin_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="surrogateescape")
        except UnicodeDecodeError:
            continue
        lines = raw.splitlines(keepends=True)
        if not lines or not lines[0].startswith("#!"):
            continue
        if "/OpenBB/.venv/" not in lines[0] and "/OpenBB/venv/" not in lines[0]:
            continue
        if lines[0] == expected:
            continue
        changed.append(path)
        if not dry_run:
            lines[0] = expected
            path.write_text("".join(lines), encoding="utf-8", errors="surrogateescape")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair moved OpenBB venv console-script shebangs.")
    parser.add_argument("--venv", type=Path, default=Path("OpenBB/venv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    changed = repair(args.venv, dry_run=args.dry_run)
    action = "would repair" if args.dry_run else "repaired"
    for path in changed:
        print(f"{action}: {path}")
    print(f"{action}_count={len(changed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
