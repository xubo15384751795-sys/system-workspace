"""Shared writer for ML signal JSON files.

Validates output against workbench.ml_signal.v1 schema, writes to
Output/ml_signals/<release_id>/<signal_type>.json, updates the
latest/ symlink, and appends a provenance record.

Isolation guarantee: writes ONLY to Output/ml_signals/. Never touches
Data/, Harvester exports, or any path that feeds back into the pipeline.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from workbench.paths import workbench_root, workspace_root

logger = logging.getLogger(__name__)

_WB_ROOT = workbench_root()
_CONTRACTS = _WB_ROOT / "packages" / "workbench" / "contracts" / "workbench"
if not _CONTRACTS.is_dir():
    logger.warning(
        "Using deprecated contracts symlink; migrate to packages/workbench/contracts"
    )
    _CONTRACTS = _WB_ROOT / "contracts" / "workbench"
_OUTPUT_ROOT = workspace_root() / "Output" / "ml_signals"
_SCHEMA_FILE = _CONTRACTS / "ml_signal.schema.json"
_MANIFEST_SCHEMA_FILE = _CONTRACTS / "ml_signal_manifest.schema.json"


# ---------------------------------------------------------------------------
# Lightweight inline schema validator (no jsonschema dependency required)
# ---------------------------------------------------------------------------

def _load_schema(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _validate_signal(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    schema = _load_schema(_SCHEMA_FILE)
    for field in schema.get("required", []):
        if field not in payload:
            errors.append(f"missing required field: {field}")
    if payload.get("schema_version") != "workbench.ml_signal.v1":
        errors.append("schema_version must be 'workbench.ml_signal.v1'")
    sig_type = payload.get("signal_type")
    if sig_type not in ("regime", "factor"):
        errors.append(f"unknown signal_type: {sig_type!r}")
    if sig_type == "regime":
        regime = payload.get("regime", {})
        probs = (regime.get("state_probs") or {})
        for key in ("compression", "volatile", "crisis"):
            if key not in probs:
                errors.append(f"regime.state_probs missing key: {key}")
        total = sum(float(v) for v in probs.values() if isinstance(v, (int, float)))
        if abs(total - 1.0) > 0.02:
            errors.append(f"regime.state_probs must sum to ~1.0, got {total:.4f}")
        current = regime.get("current")
        if current not in ("compression", "volatile", "crisis"):
            errors.append(f"regime.current must be one of compression/volatile/crisis, got {current!r}")
    if sig_type == "factor":
        factors = payload.get("factors")
        if not isinstance(factors, list) or not factors:
            errors.append("factors must be a non-empty list when signal_type == 'factor'")
    gate = payload.get("freshness_gate", {})
    if not gate.get("stale_if_release_changes"):
        errors.append("freshness_gate.stale_if_release_changes must be true")
    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class MLSignalWriteError(Exception):
    pass


def write_signal(
    payload: dict[str, Any],
    *,
    output_root: Path | None = None,
    validate: bool = True,
    artifact_basename: str | None = None,
) -> Path:
    """Validate *payload* and write it to Output/ml_signals/<release>/<name>.json.

    When *artifact_basename* is set (e.g. ``\"regime_hmm\"``), the file name is
    ``{artifact_basename}.json`` instead of default ``{signal_type}.json`` — this
    allows multiple regime artefacts in one release without schema changes.

    Returns the path of the written file.
    Raises MLSignalWriteError on validation failure.
    """
    if validate:
        errors = _validate_signal(payload)
        if errors:
            raise MLSignalWriteError("Signal validation failed:\n  - " + "\n  - ".join(errors))

    root = output_root or _OUTPUT_ROOT
    release_id = str(payload.get("source_release", "unknown"))
    sig_type = str(payload.get("signal_type", "unknown"))
    release_dir = root / release_id
    release_dir.mkdir(parents=True, exist_ok=True)

    fname = f"{artifact_basename}.json" if artifact_basename else f"{sig_type}.json"
    out_path = release_dir / fname
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    _update_latest_symlink(root, release_dir)
    _append_provenance(root, payload, out_path)
    return out_path


def write_manifest(
    signals: list[dict[str, Any]],
    source_release: str,
    *,
    output_root: Path | None = None,
) -> Path:
    """Write a manifest.json listing all signals for this release."""
    root = output_root or _OUTPUT_ROOT
    release_dir = root / source_release
    release_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for sig in signals:
        sig_type = str(sig.get("signal_type", "unknown"))
        path_rel = str(sig.get("path") or f"{sig_type}.json")
        entries.append({
            "signal_type": sig_type,
            "method": str(sig.get("method", "")),
            "path": path_rel,
            "status": "ok" if (release_dir / path_rel).exists() else "error",
        })

    manifest = {
        "schema_version": "workbench.ml_signal_manifest.v1",
        "source_release": source_release,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signals": entries,
    }
    manifest_path = release_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_latest_symlink(root: Path, target: Path) -> None:
    latest = root / "latest"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(target.name)
    except OSError:
        logger.warning("Failed to update ML signal latest symlink: %s", latest, exc_info=True)


def _append_provenance(root: Path, payload: dict[str, Any], signal_path: Path) -> None:
    prov_file = root / "provenance.jsonl"
    record = {
        "written_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signal_type": payload.get("signal_type"),
        "source_release": payload.get("source_release"),
        "method": payload.get("method"),
        "path": str(signal_path),
        "provenance": payload.get("provenance"),
    }
    try:
        with prov_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        logger.warning("Failed to append ML signal provenance: %s", prov_file, exc_info=True)


# ---------------------------------------------------------------------------
# CLI helper
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate and write an ML signal JSON.")
    parser.add_argument("signal_file", type=Path)
    parser.add_argument("--output-root", type=Path, default=None)
    args = parser.parse_args()

    raw = json.loads(args.signal_file.read_text(encoding="utf-8"))
    try:
        written = write_signal(raw, output_root=args.output_root)
        print(f"OK: {written}")
    except MLSignalWriteError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
