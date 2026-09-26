"""Unified artifact provenance schema (Phase B3).

Every consumable artifact carries a 10-field provenance block so downstream
consumers can verify identity (run_id), origin (producer_step, producer_commit,
source_release_id), timing (generated_at, as_of_date), inputs
(input_fingerprints), and validity (validation_verdict, claim_ceiling,
degraded_reasons) before reading.

Stamping strategy:
- JSON leaf artifacts (sigma_vector.json, framework_output.json) carry the
  provenance block in-body under a ``provenance`` key.
- Parquet / non-JSON artifacts carry provenance via the per-run sidecar
  ``artifact_index.json`` (extended in run_bundle.record_artifact).
- Consumers verify via ``verify_provenance`` before reading.
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verity.runtime.runtime_io import ROOT

logger = logging.getLogger(__name__)

PROVENANCE_FIELDS = (
    "run_id",
    "producer_step",
    "producer_commit",
    "source_release_id",
    "generated_at",
    "as_of_date",
    "input_fingerprints",
    "validation_verdict",
    "claim_ceiling",
    "degraded_reasons",
)


def current_bundle_run_id() -> str:
    """The bundle run_id, published by the executor via env var."""
    return os.environ.get("ZCODE_BUNDLE_RUN_ID", "")


def current_commit() -> str:
    """Best-effort git commit SHA of the working tree."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()[:12]
    except Exception:
        logger.warning("Unable to determine current git commit for provenance", exc_info=True)
    return ""


def fingerprint_inputs(paths: list[str | Path]) -> dict[str, str]:
    """Return {rel_path: sha256[:16]} for each existing input file."""
    fps: dict[str, str] = {}
    for p in paths:
        path = Path(p)
        if not path.exists():
            continue
        try:
            h = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            try:
                rel = str(path.relative_to(ROOT))
            except ValueError:
                rel = str(path)
            fps[rel] = h
        except OSError:
            logger.warning("Unable to fingerprint provenance input: %s", path, exc_info=True)
    return fps


def build_provenance(
    *,
    producer_step: str,
    source_release_id: str = "",
    as_of_date: str = "",
    input_paths: list[str | Path] | None = None,
    validation_verdict: str = "pass",
    claim_ceiling: str | None = None,
    degraded_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Build a 10-field provenance block for stamping on an artifact."""
    return {
        "run_id": current_bundle_run_id(),
        "producer_step": producer_step,
        "producer_commit": current_commit(),
        "source_release_id": source_release_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of_date": as_of_date,
        "input_fingerprints": fingerprint_inputs(input_paths or []),
        "validation_verdict": validation_verdict,
        "claim_ceiling": claim_ceiling,
        "degraded_reasons": degraded_reasons or [],
    }


def stamp_provenance(
    artifact_path: Path,
    provenance: dict[str, Any],
) -> None:
    """Stamp a ``provenance`` block into a JSON artifact's body.

    No-op (returns) for non-JSON files - those use the sidecar index.
    """
    if not artifact_path.exists() or artifact_path.suffix != ".json":
        return
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(data, dict):
        return
    data["provenance"] = provenance
    artifact_path.write_text(
        __import__("json").dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def verify_provenance(
    artifact_path: Path,
    *,
    require_run_id: bool = True,
    expected_run_id: str | None = None,
) -> tuple[bool, str]:
    """Verify a JSON artifact's provenance block.

    Returns (ok, reason). Checks:
    - artifact has a ``provenance`` block with a run_id
    - if expected_run_id given, it matches (rejects stale/previous-run artifacts)
    """
    import json

    if not artifact_path.exists():
        return False, "missing"
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"unparseable: {exc}"
    if not isinstance(data, dict):
        return False, "not a dict"
    prov = data.get("provenance")
    if not isinstance(prov, dict):
        return False, "no provenance block"
    run_id = prov.get("run_id")
    if require_run_id and not run_id:
        return False, "provenance missing run_id"
    if expected_run_id and run_id != expected_run_id:
        return False, f"run_id mismatch: expected {expected_run_id}, got {run_id}"
    return True, "ok"


# Late import to avoid circular at module load.
import json  # noqa: E402
