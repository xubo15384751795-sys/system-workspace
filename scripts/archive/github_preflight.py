#!/usr/bin/env python3
"""Preflight checks before publishing workspace content to GitHub."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    "__pycache__",
}

RISKY_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.env",
    "*.local.json",
    "*.secret.*",
    "*.pem",
    "*.key",
]

RISKY_DIR_NAMES = [
    ".claude",
    ".idea",
    ".venv",
    "venv",
    "node_modules",
]

GENERATED_DIR_PATHS = {
    "Data",
    "Output",
    "deformation-framework/output",
    "Workbench/Data",
}

LARGE_FILE_BYTES = 10 * 1024 * 1024


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def should_skip(path: Path) -> bool:
    return any(part in IGNORE_DIRS for part in path.parts)


def matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def main() -> int:
    risky_files: list[Path] = []
    risky_dirs: list[Path] = []
    generated_dirs: list[Path] = []
    large_files: list[tuple[Path, int]] = []

    for current, dirs, files in os.walk(ROOT):
        current_path = Path(current)

        dirs[:] = [
            d
            for d in dirs
            if d not in IGNORE_DIRS
        ]

        for dirname in list(dirs):
            dir_path = current_path / dirname
            if dirname in RISKY_DIR_NAMES:
                risky_dirs.append(dir_path)
                dirs.remove(dirname)
            elif rel(dir_path) in GENERATED_DIR_PATHS:
                generated_dirs.append(dir_path)
                dirs.remove(dirname)

        for filename in files:
            file_path = current_path / filename
            if should_skip(file_path):
                continue
            if matches_any(filename, RISKY_FILE_PATTERNS):
                risky_files.append(file_path)
            try:
                size = file_path.stat().st_size
            except OSError:
                continue
            if size >= LARGE_FILE_BYTES:
                large_files.append((file_path, size))

    print("GitHub preflight report")
    print("=======================")

    if risky_files:
        print("\nSensitive/local files present:")
        for path in risky_files:
            print(f"  - {rel(path)}")

    if risky_dirs:
        print("\nLocal tool or dependency directories present:")
        for path in risky_dirs:
            print(f"  - {rel(path)}/")

    if generated_dirs:
        print("\nGenerated data/output directories present:")
        for path in generated_dirs:
            print(f"  - {rel(path)}/")

    if large_files:
        print("\nLarge files present:")
        for path, size in sorted(large_files, key=lambda item: item[1], reverse=True):
            mib = size / (1024 * 1024)
            print(f"  - {rel(path)} ({mib:.1f} MiB)")

    if not any([risky_files, risky_dirs, generated_dirs, large_files]):
        print("\nNo obvious GitHub publishing risks found.")
        return 0

    print(
        "\nThese may be fine locally, but verify they are ignored or excluded "
        "before staging commits."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
