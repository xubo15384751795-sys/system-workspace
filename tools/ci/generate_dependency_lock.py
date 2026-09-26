#!/usr/bin/env python3
"""Audit the historical compatibility requirements lock.

The workspace dependency authority is ``uv.lock``.  This command is retained
only for migration/reference audits of ``requirements.lock.txt`` and must not
be used to provision the workspace or replace the uv resolver.

The previous lock was produced by `pip freeze | grep -iE "^(pyyaml|jsonschema
|pandas|numpy|scikit-learn|hmmlearn|ruff|pytest)"` — a hand-written list of
eight names. It missed omegaconf, mcp and mypy, which requirements-dev.txt
declares directly, and every transitive dependency. Eight pins against 461
installed packages is not a reproducible environment, which is what P0-2's
clean-checkout reproduction evidence needs.

This walks the actual closure instead: start from what the project declares
(requirements-dev.txt plus each pyproject's core dependencies and `dev`
extra), follow `requires_dist` through installed metadata with environment
markers evaluated for the current interpreter, and pin every package reached
to its installed version.

Deliberately not a `pip freeze`: that would capture the whole interpreter,
including packages this project never imports, and pin them as if they were
requirements.

Usage:
    python3 -m scripts.commands.ci.generate_dependency_lock            # check
    python3 -m scripts.commands.ci.generate_dependency_lock --write \
        --allow-legacy-compatibility-write                              # rewrite legacy file

``--write`` updates the historical compatibility file only; it does not
modify ``uv.lock`` and the generated file must not be installed directly.

Exit codes:
    0  lock is current (or was rewritten with --write)
    1  lock is stale — run with --write
    2  a declared dependency is not installed, so the closure is incomplete
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = ROOT / "requirements.lock.txt"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"
PYPROJECTS = [ROOT / "pyproject.toml", *sorted(ROOT.glob("packages/*/pyproject.toml"))]

# Extras installed by .github/workflows/ci.yml. Optional extras that CI does
# not install (torch, jax, openbb, streamlit...) are out of the reproducible
# surface and must not be pinned — pinning them would imply the project
# requires them.
LOCKED_EXTRAS = ("dev",)

HEADER = """\
# Historical compatibility dependency pins; not the workspace authority.
#
# The workspace authority is uv.lock at the repository root. Use
# `uv sync --locked --all-packages`; do not install this file directly.
#
# Generated — do not edit by hand:
#     python3 -m scripts.commands.ci.generate_dependency_lock --write
#
# Contents: the transitive closure of what the project declares
# (requirements-dev.txt plus each pyproject's dependencies and `dev` extra),
# resolved against installed metadata with environment markers evaluated.
# Optional extras CI does not install (torch, jax, openbb, ...) are excluded
# on purpose: pinning them would imply the project requires them.
#
# This file is retained only for migration/reference audits.
"""


def _declared_roots() -> set[str]:
    """Every distribution the project declares directly."""
    roots: set[str] = set()

    if DEV_REQUIREMENTS.exists():
        for line in DEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            roots.add(canonicalize_name(Requirement(line).name))

    for pyproject in PYPROJECTS:
        if not pyproject.exists():
            continue
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        specs = list(project.get("dependencies", []) or [])
        optional = project.get("optional-dependencies", {}) or {}
        for extra in LOCKED_EXTRAS:
            specs.extend(optional.get(extra, []) or [])
        for spec in specs:
            name = canonicalize_name(Requirement(spec).name)
            # Self-referential extras (`pkg[ml,dev]`) resolve through the
            # pyprojects already being walked.
            if name in {canonicalize_name(p.get("project", {}).get("name", ""))
                        for p in (tomllib.loads(f.read_text(encoding="utf-8"))
                                  for f in PYPROJECTS if f.exists())}:
                continue
            roots.add(name)
    return roots


def resolve_closure(roots: set[str]) -> tuple[dict[str, str], list[str]]:
    """Return (name -> installed version, missing declared names)."""
    env = dict(default_environment())
    pinned: dict[str, str] = {}
    missing: list[str] = []
    queue = sorted(roots)
    seen: set[str] = set()

    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            if name in roots:
                missing.append(name)
            continue
        pinned[canonicalize_name(dist.metadata["Name"])] = dist.version
        for raw in dist.requires or []:
            req = Requirement(raw)
            # Skip requirements gated behind an extra we do not install, and
            # those whose markers exclude this interpreter.
            if req.marker is not None and not req.marker.evaluate(env):
                continue
            queue.append(canonicalize_name(req.name))
    return pinned, missing


def render(pinned: dict[str, str]) -> str:
    lines = [HEADER]
    for name in sorted(pinned):
        lines.append(f"{name}=={pinned[name]}")
    return "\n".join(lines) + "\n"


def _normalize(text: str) -> list[str]:
    """Comparable pin list, ignoring comments and blank lines."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Rewrite the legacy compatibility file.")
    parser.add_argument(
        "--allow-legacy-compatibility-write",
        action="store_true",
        help="Explicitly authorize rewriting requirements.lock.txt; never changes uv.lock.",
    )
    args = parser.parse_args(argv)
    if args.write and not args.allow_legacy_compatibility_write:
        parser.error(
            "--write is compatibility-only; add --allow-legacy-compatibility-write explicitly"
        )
    if args.allow_legacy_compatibility_write and not args.write:
        parser.error("--allow-legacy-compatibility-write requires --write")

    roots = _declared_roots()
    pinned, missing = resolve_closure(roots)

    if missing:
        print(
            "declared but not installed, closure incomplete: "
            + ", ".join(sorted(missing)),
            file=sys.stderr,
        )
        return 2

    rendered = render(pinned)
    current = LOCK_PATH.read_text(encoding="utf-8") if LOCK_PATH.exists() else ""

    if args.write:
        LOCK_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {LOCK_PATH.relative_to(ROOT)} — {len(pinned)} pins")
        return 0

    if _normalize(current) != _normalize(rendered):
        have, want = set(_normalize(current)), set(_normalize(rendered))
        print(f"lock is stale: {len(have)} pins on disk, {len(want)} in closure")
        for extra in sorted(have - want)[:10]:
            print(f"  - {extra}")
        for missed in sorted(want - have)[:10]:
            print(f"  + {missed}")
        print(
            "run only for legacy compatibility maintenance: "
            "python3 -m scripts.commands.ci.generate_dependency_lock "
            "--write --allow-legacy-compatibility-write"
        )
        return 1

    print(f"lock is current — {len(pinned)} pins")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
