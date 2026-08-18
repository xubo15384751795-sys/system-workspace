"""Read-only canonical lineage bridge for orchestration shadow runs.

The daily executor historically returned step status only.  During the
orchestration migration we may expose canonical IDs that a step has already
written, but only when the output belongs to the current run and validates as
the frozen Observation -> Measurement -> Evidence -> Claim contract.  This
module never creates IDs, changes authority, or publishes an output.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts._runtime_io import current_dir, surface_dir
from system_runtime.canonical_ids import lineage_ids, validate_chain
from system_runtime.paths import WorkspacePaths

ROOT = WorkspacePaths.discover().root


def _output_path(raw_path: str | os.PathLike[str]) -> Path:
    """Resolve a registry output path against the active output surface."""

    path = Path(raw_path)
    if path.is_absolute():
        return path

    text = path.as_posix()
    if text.startswith("Output/"):
        parts = text.split("/", 2)
        if len(parts) == 3:
            # surface_dir honors CURRENT_OUTPUT_DIR and generation-mode
            # candidate surfaces, so a previous published Output/current is
            # never read accidentally during a transactional run.
            surface = current_dir() if parts[1] == "current" else surface_dir(parts[1])
            return surface / parts[2]
        return ROOT / path
    return ROOT / path


def _validated_lineage(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a compact validated lineage envelope, if one is present."""

    chain = payload.get("canonical_chain")
    if not isinstance(chain, Mapping):
        return None
    chain_dict = dict(chain)
    try:
        validate_chain(chain_dict)
    except (TypeError, ValueError):
        return None
    return {
        "canonical_chain": chain_dict,
        "canonical_ids": lineage_ids(chain_dict),
    }


def read_output_lineage(
    output_paths: Sequence[str],
    *,
    run_id: str,
) -> dict[str, Any] | None:
    """Read the first current-run canonical chain from declared outputs.

    A run stamp is mandatory.  This is the stale-output guard: an otherwise
    valid chain from a prior `Output/current` surface is not attached to a new
    execution result.
    """

    expected_run_id = str(run_id or "").strip()
    if not expected_run_id:
        return None

    for raw_path in output_paths:
        path = _output_path(raw_path)
        if path.suffix.lower() != ".json" or not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, Mapping) or str(payload.get("run_id", "")) != expected_run_id:
            continue
        lineage = _validated_lineage(payload)
        if lineage is None:
            continue
        lineage["canonical_source_path"] = str(path)
        return lineage
    return None


def attach_output_lineage(
    result: dict[str, Any],
    output_paths: Sequence[str],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Attach validated current-run lineage to a step result, additively."""

    if result.get("status") not in {"success", "degraded"}:
        return result
    if isinstance(result.get("canonical_ids"), Mapping):
        return result
    lineage = read_output_lineage(output_paths, run_id=run_id)
    if lineage is None:
        return result
    result.update(lineage)
    return result


__all__ = ["attach_output_lineage", "read_output_lineage"]
