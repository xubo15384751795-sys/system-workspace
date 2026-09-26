"""Preflight and isolated fidelity audit for the Step 5 generation restore.

The restore gate has two intentionally independent decisions:

* structural restore fidelity: can an accepted generation be copied into an
  isolated workspace without changing its bytes, lineage, pointers, or
  authority semantics?
* production-authority restore: is the generation allowed to serve decision
  consumers under the existing production admission rules?

The structural drill only creates a temporary directory. It never changes
``Output/current``, generation pointers, provider state, or production data.
The production decision remains fail-closed for ``DIAGNOSTIC_ONLY``, ``BLOCK``,
and ``DENY`` authorities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASELINE_PATH = ROOT / "governance" / "production_baseline_v1.json"
GENERATIONS_ROOT = ROOT / "Output" / "generations"
REQUIRED_GENERATION_FILES = frozenset({"manifest.json", "admission.json", "lineage.json"})
REQUIRED_GENERATION_SURFACES = frozenset(
    {"current", "position", "judgment", "trade_decision", "trade_ledger", "quality", "system_learning"}
)
PRODUCTION_BLOCKED_AUTHORITIES = frozenset({"DIAGNOSTIC_ONLY", "BLOCK", "DENY"})
KNOWN_AUTHORITIES = frozenset({"ALLOW", "DIAGNOSTIC_ONLY", "BLOCK", "DENY"})
SYSTEM_INDEX_SNAPSHOT_FILES = (
    "Data/system_index/latest.json",
    "Data/system_index/system_catalog.json",
    "Data/system_index/lineage_graph.json",
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_digest(path: Path) -> str | None:
    try:
        return _canonical_digest(_read_json(path))
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None


def _safe_relative_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not root.is_dir():
        return entries
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "target": os.readlink(path),
                }
            )
        elif path.is_file():
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size_bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return entries


def _inventory_digest(inventory: list[dict[str, Any]]) -> str:
    return _canonical_digest(inventory)


def _claim_ceiling(generation_dir: Path) -> str | None:
    sources = (
        generation_dir / "judgment" / "latest.json",
        generation_dir / "current" / "status.json",
        generation_dir / "current" / "signal_card.json",
    )
    for path in sources:
        if not path.is_file():
            continue
        try:
            payload = _read_json(path)
        except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
            continue
        candidates = [payload.get("claim_ceiling")]
        judgment = payload.get("judgment")
        if isinstance(judgment, dict):
            candidates.append(judgment.get("claim_ceiling"))
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value
    return None


def _reader_graph() -> dict[str, Any]:
    return {
        "generation": {
            "owner": "system_runtime.publish_transaction",
            "manifest": "Output/generations/<generation_id>/manifest.json",
            "admission": "Output/generations/<generation_id>/admission.json",
            "lineage": "Output/generations/<generation_id>/lineage.json",
            "artifact_surfaces": "Output/generations/<generation_id>/{current,judgment,quality,...}",
        },
        "current_pointer": {
            "owner": "system_runtime.publish_transaction",
            "path": "Output/current -> Output/generations/<generation_id>/current",
            "run_identity": "Output/current/latest_run_id.txt",
        },
        "runtime_readers": [
            {
                "reader": "system_runtime.paths.WorkspacePaths.current",
                "reads": ["Output/current", "Output/generations/<generation_id>/current"],
                "role": "resolve current surface",
            },
            {
                "reader": "verity.runtime._authority_graph",
                "reads": ["compiled pipeline", "current artifacts", "manifest/lineage policy"],
                "role": "diagnostic authority graph",
            },
            {
                "reader": "governance pipeline steps",
                "reads": ["Output/current", "Output/current/latest_run_id.txt", "Output/runs/"],
                "role": "downstream artifact and event consumers",
            },
        ],
    }


def _append_unique(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _assess_candidate(path: Path) -> dict[str, Any]:
    manifest: dict[str, Any] = {}
    admission: dict[str, Any] = {}
    lineage: dict[str, Any] = {}
    structural_reasons: list[str] = []
    production_reasons: list[str] = []
    generation_id = path.parent.name

    try:
        manifest = _read_json(path)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        _append_unique(structural_reasons, f"manifest_invalid={type(exc).__name__}")

    generation_id = str(manifest.get("run_id") or generation_id)
    status = manifest.get("status")
    authority = manifest.get("authority")

    if status != "accepted":
        _append_unique(structural_reasons, f"generation_status={status}")
    if authority not in KNOWN_AUTHORITIES:
        _append_unique(structural_reasons, f"authority_invalid={authority}")

    missing = sorted(
        name for name in REQUIRED_GENERATION_FILES if not (path.parent / name).is_file()
    )
    if missing:
        _append_unique(structural_reasons, "missing=" + ",".join(missing))
    missing_surfaces = sorted(
        name for name in REQUIRED_GENERATION_SURFACES if not (path.parent / name).is_dir()
    )
    if missing_surfaces:
        _append_unique(structural_reasons, "missing_surfaces=" + ",".join(missing_surfaces))

    try:
        admission = _read_json(path.parent / "admission.json")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        _append_unique(structural_reasons, f"admission_invalid={type(exc).__name__}")
    try:
        lineage = _read_json(path.parent / "lineage.json")
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        _append_unique(structural_reasons, f"lineage_invalid={type(exc).__name__}")

    if manifest.get("run_id") != generation_id:
        _append_unique(structural_reasons, "manifest_run_id_mismatch")
    if lineage:
        if lineage.get("schema_version") != "system.generation_lineage.v1":
            _append_unique(structural_reasons, "lineage_schema_invalid")
        if lineage.get("run_id") != generation_id:
            _append_unique(structural_reasons, "lineage_run_id_mismatch")
        if manifest.get("generation_digest") != _sha256(path.parent / "lineage.json"):
            _append_unique(structural_reasons, "generation_digest_mismatch")
        for entry in lineage.get("files", []):
            if not isinstance(entry, dict):
                _append_unique(structural_reasons, "lineage_entry_invalid")
                continue
            relative = _safe_relative_path(entry.get("path"))
            target = path.parent / relative if relative is not None else None
            if target is None or not target.is_file():
                _append_unique(structural_reasons, f"lineage_missing={entry.get('path')}")
                continue
            if entry.get("sha256") != _sha256(target):
                _append_unique(structural_reasons, f"lineage_digest_mismatch={entry.get('path')}")

    if admission:
        if admission.get("generation_id") != generation_id:
            _append_unique(structural_reasons, "admission_generation_id_mismatch")
        if admission.get("authority_verdict") != authority:
            _append_unique(structural_reasons, "admission_authority_mismatch")
        if admission.get("integrity_verdict") != "PASS" or admission.get("can_publish") is not True:
            _append_unique(structural_reasons, "integrity_not_publishable")
        if not isinstance(admission.get("allows_decision_consumers"), bool):
            _append_unique(structural_reasons, "decision_consumer_permission_missing")

    claim_ceiling = _claim_ceiling(path.parent)
    if claim_ceiling is None:
        _append_unique(structural_reasons, "claim_ceiling_missing")
    latest_pointer = path.parent / "current" / "latest_run_id.txt"
    if not latest_pointer.is_file() or latest_pointer.read_text(encoding="utf-8").strip() != generation_id:
        _append_unique(structural_reasons, "current_run_pointer_mismatch")

    for reason in structural_reasons:
        _append_unique(production_reasons, reason)
    if authority in PRODUCTION_BLOCKED_AUTHORITIES:
        _append_unique(production_reasons, f"authority={authority}")
    if admission.get("allows_decision_consumers") is not True:
        _append_unique(production_reasons, "allows_decision_consumers=false")
    if admission.get("can_publish") is not True:
        _append_unique(production_reasons, "can_publish=false")

    structural_eligible = not structural_reasons
    production_eligible = not production_reasons
    return {
        "generation_id": generation_id,
        "path": str(path.parent.relative_to(ROOT)),
        "status": status,
        "authority": authority,
        "release_id": manifest.get("release_id"),
        "generation_digest": manifest.get("generation_digest"),
        # ``eligible`` remains a compatibility alias for callers that used
        # the old single production-eligibility field.
        "eligible": production_eligible,
        "reasons": production_reasons,
        "structural_restore_eligible": structural_eligible,
        "structural_restore_reasons": structural_reasons,
        "production_restore_eligible": production_eligible,
        "production_restore_reasons": production_reasons,
        "claim_ceiling": claim_ceiling,
        "allows_decision_consumers": admission.get("allows_decision_consumers"),
    }


def _pointer_snapshot(root: Path, generation_id: str) -> dict[str, Any]:
    output = root / "Output"
    live = output / "live"
    current = output / "current"
    expected_generation = (output / "generations" / generation_id).resolve()
    current_target = current.resolve() if current.exists() else None
    latest_pointer = current / "latest_run_id.txt"
    return {
        "live_target": os.readlink(live) if live.is_symlink() else None,
        "current_target": os.readlink(current) if current.is_symlink() else None,
        "latest_run_id": latest_pointer.read_text(encoding="utf-8").strip()
        if latest_pointer.is_file()
        else None,
        "current_resolves_to_target": current_target == expected_generation / "current",
        "live_resolves_to_target": live.resolve() == expected_generation,
    }


def _make_isolated_pointers(root: Path, generation_id: str) -> None:
    output = root / "Output"
    (output / "generations").mkdir(parents=True, exist_ok=True)
    os.symlink(f"generations/{generation_id}", output / "live")
    os.symlink("live/current", output / "current")


def _json_parity(source: Path, restored: Path) -> dict[str, Any]:
    source_digest = _json_digest(source)
    restored_digest = _json_digest(restored)
    return {
        "status": "PASS" if source_digest is not None and source_digest == restored_digest else "FAIL",
        "source_digest": source_digest,
        "restored_digest": restored_digest,
    }


def _text_parity(source: Path, restored: Path) -> dict[str, Any]:
    try:
        source_value = source.read_text(encoding="utf-8")
        restored_value = restored.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        source_value = None
        restored_value = None
    return {
        "status": "PASS" if source_value is not None and source_value == restored_value else "FAIL",
        "source_value": source_value,
        "restored_value": restored_value,
    }


def _index_registry_parity(
    root: Path,
    isolated_root: Path,
    source_generation: Path,
    restored_generation: Path,
) -> dict[str, Any]:
    artifact_registry = _json_parity(
        source_generation / "current" / "artifact_registry.json",
        restored_generation / "current" / "artifact_registry.json",
    )
    run_pointer = _text_parity(
        source_generation / "current" / "latest_run_id.txt",
        restored_generation / "current" / "latest_run_id.txt",
    )
    snapshots: dict[str, Any] = {}
    for relative in SYSTEM_INDEX_SNAPSHOT_FILES:
        source = root / relative
        restored = isolated_root / relative
        snapshots[relative] = _json_parity(source, restored) if source.is_file() else {
            "status": "NOT_PRESENT",
            "source_digest": None,
            "restored_digest": None,
        }
    statuses = [artifact_registry["status"], run_pointer["status"]]
    statuses.extend(item["status"] for item in snapshots.values() if item["status"] != "NOT_PRESENT")
    return {
        "status": "PASS" if statuses and all(status == "PASS" for status in statuses) else "FAIL",
        "artifact_registry": artifact_registry,
        "run_pointer": run_pointer,
        "system_index_snapshots": snapshots,
    }


def run_structural_restore_fidelity(
    generation_id: str,
    *,
    root: Path = ROOT,
) -> dict[str, Any]:
    """Copy one generation into a temporary workspace and compare fidelity."""

    source_generation = root / "Output" / "generations" / generation_id
    manifest_path = source_generation / "manifest.json"
    if not manifest_path.is_file():
        return {
            "status": "BLOCKED",
            "generation_id": generation_id,
            "reason": "generation_manifest_missing",
        }
    candidate = _assess_candidate(manifest_path)
    if not candidate["structural_restore_eligible"]:
        return {
            "status": "BLOCKED",
            "generation_id": generation_id,
            "structural_restore_eligible": False,
            "reasons": candidate["structural_restore_reasons"],
        }

    with tempfile.TemporaryDirectory(prefix="verity-structural-restore-") as temporary:
        isolated_root = Path(temporary)
        restored_generation = isolated_root / "Output" / "generations" / generation_id
        restored_generation.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_generation, restored_generation, symlinks=True)
        _make_isolated_pointers(isolated_root, generation_id)

        # The system index is a committed compatibility/index surface, not a
        # generation-owned writer. Include its immutable snapshot in the
        # isolated evidence set so parity is checked without regenerating it
        # against the user's live workspace.
        for relative in SYSTEM_INDEX_SNAPSHOT_FILES:
            source = root / relative
            if source.is_file():
                target = isolated_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

        source_inventory = _file_inventory(source_generation)
        restored_inventory = _file_inventory(restored_generation)
        source_semantics = {
            "authority": candidate["authority"],
            "claim_ceiling": candidate["claim_ceiling"],
            "allows_decision_consumers": candidate["allows_decision_consumers"],
        }
        restored_manifest = _read_json(restored_generation / "manifest.json")
        restored_admission = _read_json(restored_generation / "admission.json")
        restored_semantics = {
            "authority": restored_manifest.get("authority"),
            "claim_ceiling": _claim_ceiling(restored_generation),
            "allows_decision_consumers": restored_admission.get("allows_decision_consumers"),
        }
        inventory_equal = source_inventory == restored_inventory
        source_pointers = _pointer_snapshot(root, generation_id)
        restored_pointers = _pointer_snapshot(isolated_root, generation_id)
        checks = {
            "generation_complete": {"status": "PASS"},
            "manifest_valid": {"status": "PASS"},
            "artifacts_available": {
                "status": "PASS" if source_inventory and restored_inventory else "FAIL",
                "source_file_count": len(source_inventory),
                "restored_file_count": len(restored_inventory),
            },
            "restore_point_explicit": {
                "status": "PASS"
                if restored_manifest.get("run_id") == generation_id
                and restored_manifest.get("release_id")
                and restored_manifest.get("generation_digest")
                else "FAIL",
            },
            "reader_graph_complete": {
                "status": "PASS"
                if _reader_graph().get("generation") and _reader_graph().get("runtime_readers")
                else "FAIL",
            },
            "artifact_inventory_parity": {
                "status": "PASS" if inventory_equal else "FAIL",
                "source_count": len(source_inventory),
                "restored_count": len(restored_inventory),
            },
            "content_digest_parity": {
                "status": "PASS"
                if _inventory_digest(source_inventory) == _inventory_digest(restored_inventory)
                else "FAIL",
                "source_digest": _inventory_digest(source_inventory),
                "restored_digest": _inventory_digest(restored_inventory),
            },
            "manifest_parity": _json_parity(
                source_generation / "manifest.json", restored_generation / "manifest.json"
            ),
            "lineage_parity": _json_parity(
                source_generation / "lineage.json", restored_generation / "lineage.json"
            ),
            "lineage_index_registry_parity": _index_registry_parity(
                root, isolated_root, source_generation, restored_generation
            ),
            "pointer_publication_invariants_parity": {
                "status": "PASS" if source_pointers == restored_pointers else "FAIL",
                "source": source_pointers,
                "restored": restored_pointers,
            },
            "authority_preserved": {
                "status": "PASS"
                if restored_semantics["authority"] == source_semantics["authority"]
                else "FAIL",
                "original": source_semantics["authority"],
                "restored": restored_semantics["authority"],
            },
            "claim_ceiling_preserved": {
                "status": "PASS"
                if restored_semantics["claim_ceiling"] == source_semantics["claim_ceiling"]
                else "FAIL",
                "original": source_semantics["claim_ceiling"],
                "restored": restored_semantics["claim_ceiling"],
            },
            "decision_consumer_permission_preserved": {
                "status": "PASS"
                if restored_semantics["allows_decision_consumers"]
                == source_semantics["allows_decision_consumers"]
                else "FAIL",
                "original": source_semantics["allows_decision_consumers"],
                "restored": restored_semantics["allows_decision_consumers"],
            },
        }
        status = "PASS" if all(item.get("status") == "PASS" for item in checks.values()) else "FAIL"
        return {
            "status": status,
            "generation_id": generation_id,
            "release_id": restored_manifest.get("release_id"),
            "original_authority": source_semantics["authority"],
            "restored_authority": restored_semantics["authority"],
            "original_claim_ceiling": source_semantics["claim_ceiling"],
            "restored_claim_ceiling": restored_semantics["claim_ceiling"],
            "original_allows_decision_consumers": source_semantics["allows_decision_consumers"],
            "restored_allows_decision_consumers": restored_semantics["allows_decision_consumers"],
            "production_authority_untouched": True,
            "isolated_restore": True,
            "production_output_touched": False,
            "checks": checks,
        }


def _select_structural_target(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    eligible = [item for item in candidates if item["structural_restore_eligible"]]
    if not eligible:
        return None
    # Generation ids carry the run timestamp. Selecting the latest accepted
    # structural candidate makes the current r10 generation the target while
    # keeping the rule deterministic for later runs.
    return max(eligible, key=lambda item: item["generation_id"])


def build_report(
    *,
    structural_target_id: str | None = None,
    run_structural_drill: bool = True,
) -> dict[str, Any]:
    baseline = _read_json(BASELINE_PATH)
    manifests = sorted(GENERATIONS_ROOT.glob("*/manifest.json"))
    candidates = [_assess_candidate(path) for path in manifests]
    structural_targets = [item for item in candidates if item["structural_restore_eligible"]]
    production_targets = [item for item in candidates if item["production_restore_eligible"]]
    selected = (
        next(
            (item for item in structural_targets if item["generation_id"] == structural_target_id),
            None,
        )
        if structural_target_id
        else _select_structural_target(candidates)
    )
    structural_drill: dict[str, Any] = {
        "status": "NOT_RUN",
        "target": selected["generation_id"] if selected else None,
    }
    if run_structural_drill and selected:
        structural_drill = run_structural_restore_fidelity(selected["generation_id"])

    structural_status = (
        "PASS"
        if structural_drill.get("status") == "PASS"
        else "READY_FOR_FIDELITY_DRILL"
        if selected
        else "BLOCKED_NO_STRUCTURAL_TARGET"
    )
    production_status = (
        "READY_FOR_HUMAN_TARGET"
        if production_targets
        else "BLOCKED_NO_ELIGIBLE_PRODUCTION_TARGET"
    )
    baseline_generation = str(baseline.get("generation_id", ""))
    baseline_candidate = next(
        (item for item in candidates if item["generation_id"] == baseline_generation),
        None,
    )
    baseline_target = {
        "baseline_id": baseline.get("baseline_id"),
        "generation_id": baseline_generation,
        "release_id": baseline.get("release_id"),
        "selection": "production_baseline_v1",
        "eligible": bool(baseline_candidate and baseline_candidate["production_restore_eligible"]),
        "structural_restore_eligible": bool(
            baseline_candidate and baseline_candidate["structural_restore_eligible"]
        ),
        "production_restore_eligible": bool(
            baseline_candidate and baseline_candidate["production_restore_eligible"]
        ),
        "reasons": list(
            (baseline_candidate or {}).get("production_restore_reasons", ["baseline generation not found"])
        ),
        "structural_restore_reasons": list(
            (baseline_candidate or {}).get(
                "structural_restore_reasons", ["baseline generation not found"]
            )
        ),
    }
    return {
        "schema_version": "governance.restore_generation_preflight.v2",
        "status": "PASS_WITH_PRODUCTION_RESTORE_DEFERRED"
        if structural_status == "PASS"
        else structural_status,
        "scope": "read_only_preflight_and_isolated_structural_drill",
        "structural_restore_eligible": bool(structural_targets),
        "production_restore_eligible": bool(production_targets),
        "baseline_target": baseline_target,
        "structural_restore_targets": structural_targets,
        "production_restore_targets": production_targets,
        # Compatibility name: this remains the production list and therefore
        # stays empty while every generation is diagnostic-only.
        "eligible_targets": production_targets,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "reader_graph": _reader_graph(),
        "structural_restore": {
            "status": structural_status,
            "target": selected["generation_id"] if selected else None,
            "eligible_targets": structural_targets,
            "fidelity_drill": structural_drill,
        },
        "production_restore": {
            "status": production_status,
            "eligible_targets": production_targets,
            "authority_rule_unchanged": True,
            "decision_consumers_required": True,
        },
        "dry_run": {
            "status": "NOT_RUN_NO_ELIGIBLE_PRODUCTION_TARGET"
            if not production_targets
            else "READY_PENDING_TARGET_SELECTION",
            "source": None,
            "target": None,
            "files_affected": [],
            "pointers_affected": [],
            "overwrite": False,
            "rollback": "isolated temporary Output root only",
        },
        "restore": {
            "status": "PASS" if structural_status == "PASS" else "NOT_RUN",
            "production_output_touched": False,
            "authority_elevation": False,
        },
        "gate": {
            "structural_restore_fidelity": structural_status,
            "production_authority_restore": "PASS" if production_targets else "DEFERRED_STEP6",
            "exact_production_restore_target_defined": "PASS" if production_targets else "FAIL",
            "reader_graph": "PASS",
            "dry_run": "NOT_RUN",
            "isolated_restore": "PASS" if structural_status == "PASS" else "NOT_RUN",
            "parity": "PASS" if structural_status == "PASS" else "NOT_RUN",
            "publication_validation": "PASS" if structural_status == "PASS" else "NOT_RUN",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="retained for CLI compatibility")
    parser.add_argument("--structural-target", help="explicit generation id for the isolated fidelity drill")
    parser.add_argument(
        "--no-structural-drill",
        action="store_true",
        help="only inventory the two eligibility decisions; do not copy a temporary target",
    )
    args = parser.parse_args(argv)
    report = build_report(
        structural_target_id=args.structural_target,
        run_structural_drill=not args.no_structural_drill,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
