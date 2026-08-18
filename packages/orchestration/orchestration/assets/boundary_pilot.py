"""Read-only four-boundary Dagster asset/check pilot.

This pilot makes the evidence-to-authority boundaries visible to Dagster.  It
does not acquire data, write Output, or replace ``PublishTransaction`` and its
serialized admission token.  Missing or stale operator artifacts therefore
produce a blocking check rather than a synthetic green asset.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dagster import AssetCheckResult, asset, asset_check

from scripts._runtime_io import ROOT


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def read_harvester_release(root: Path = ROOT) -> dict[str, Any]:
    """Read the latest release descriptors without declaring them valid."""
    manifest_path = (
        root
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "manifests"
        / "cross_asset_daily_panel.manifest.json"
    )
    quality_path = (
        root
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "quality_reports"
        / "cross_asset_daily_panel.quality.json"
    )
    manifest = _read_json(manifest_path)
    quality = _read_json(quality_path)
    provider_status = manifest.get("provider_status") or {}
    all_failed = bool(
        manifest.get("all_providers_failed")
        or provider_status.get("all_failed")
        or manifest.get("status") == "failed"
    )
    release_id = str(
        manifest.get("release_id")
        or manifest.get("release")
        or manifest.get("vintage")
        or ""
    )
    return {
        "status": "missing" if not manifest else str(manifest.get("status", "unknown")),
        "release_id": release_id,
        "manifest_path": str(manifest_path),
        "quality_path": str(quality_path),
        "manifest_exists": manifest_path.exists(),
        "quality_exists": quality_path.exists(),
        "all_providers_failed": all_failed,
        "actual_observation_end": (
            manifest.get("time_coverage", {}).get("end")
            if isinstance(manifest.get("time_coverage"), dict)
            else None
        ),
        "quality_verdict": quality.get("verdict") or quality.get("status"),
    }


def build_admitted_evidence(release: dict[str, Any]) -> dict[str, Any]:
    """Convert a release descriptor into an explicit evidence boundary."""
    blockers: list[str] = []
    if not release.get("manifest_exists"):
        blockers.append("MISSING_RELEASE_MANIFEST")
    if not release.get("quality_exists"):
        blockers.append("MISSING_RELEASE_QUALITY")
    if not release.get("release_id"):
        blockers.append("MISSING_RELEASE_ID")
    if release.get("all_providers_failed"):
        blockers.append("ALL_PROVIDERS_FAILED")
    if str(release.get("status", "")).lower() not in {"refreshed", "success", "accepted"}:
        blockers.append("RELEASE_NOT_REFRESHED")
    return {
        "status": "admitted" if not blockers else "blocked",
        "release_id": release.get("release_id"),
        "blockers": blockers,
        "source": "harvester_release",
    }


def build_diagnostic_candidate(evidence: dict[str, Any]) -> dict[str, Any]:
    """Expose a diagnostic candidate without granting decision authority."""
    admitted = evidence.get("status") == "admitted"
    return {
        "status": "ready" if admitted else "blocked",
        "release_id": evidence.get("release_id"),
        "authority_mode": "DIAGNOSTIC_ONLY",
        "blockers": list(evidence.get("blockers") or []),
        "source": "admitted_evidence",
    }


def build_decision_current(candidate: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Read decision authority as a separate boundary; never infer or grant it."""
    gate_path = root / "Output" / "judgment" / "promotion_gate.json"
    gate = _read_json(gate_path)
    authority = str(
        gate.get("decision_authority_verdict")
        or gate.get("authority_verdict")
        or gate.get("authority")
        or "DIAGNOSTIC_ONLY"
    ).upper()
    allowed = candidate.get("status") == "ready" and authority == "ALLOW"
    return {
        "status": "authorized" if allowed else "diagnostic_only",
        "release_id": candidate.get("release_id"),
        "authority_mode": "ALLOW" if allowed else "DIAGNOSTIC_ONLY",
        "promotion_gate_path": str(gate_path),
        "source": "diagnostic_candidate",
    }


@asset(name="harvester_release", compute_kind="boundary_pilot")
def harvester_release() -> dict[str, Any]:
    return read_harvester_release()


@asset(name="admitted_evidence", compute_kind="boundary_pilot")
def admitted_evidence(harvester_release: dict[str, Any]) -> dict[str, Any]:
    return build_admitted_evidence(harvester_release)


@asset(name="diagnostic_candidate", compute_kind="boundary_pilot")
def diagnostic_candidate(admitted_evidence: dict[str, Any]) -> dict[str, Any]:
    return build_diagnostic_candidate(admitted_evidence)


@asset(name="decision_current", compute_kind="boundary_pilot")
def decision_current(diagnostic_candidate: dict[str, Any]) -> dict[str, Any]:
    return build_decision_current(diagnostic_candidate)


@asset_check(
    asset=harvester_release,
    name="harvester_release_admission",
    blocking=True,
    compute_kind="boundary_pilot",
)
def harvester_release_admission(harvester_release: dict[str, Any]) -> AssetCheckResult:
    passed = bool(
        harvester_release.get("manifest_exists")
        and harvester_release.get("quality_exists")
        and not harvester_release.get("all_providers_failed")
        and harvester_release.get("release_id")
    )
    return AssetCheckResult(
        passed=passed,
        description="release manifest, quality evidence, and provider outcome are admissible",
        metadata={
            "status": harvester_release.get("status", "unknown"),
            "release_id": harvester_release.get("release_id", ""),
            "all_providers_failed": bool(harvester_release.get("all_providers_failed")),
        },
    )


@asset_check(
    asset=admitted_evidence,
    name="evidence_integrity",
    blocking=True,
    compute_kind="boundary_pilot",
)
def evidence_integrity(admitted_evidence: dict[str, Any]) -> AssetCheckResult:
    blockers = list(admitted_evidence.get("blockers") or [])
    return AssetCheckResult(
        passed=admitted_evidence.get("status") == "admitted",
        description="only admitted same-release evidence may reach diagnostic construction",
        metadata={"blockers": blockers, "release_id": admitted_evidence.get("release_id", "")},
    )


@asset_check(
    asset=diagnostic_candidate,
    name="diagnostic_authority_boundary",
    blocking=True,
    compute_kind="boundary_pilot",
)
def diagnostic_authority_boundary(diagnostic_candidate: dict[str, Any]) -> AssetCheckResult:
    passed = (
        diagnostic_candidate.get("status") == "ready"
        and diagnostic_candidate.get("authority_mode") == "DIAGNOSTIC_ONLY"
    )
    return AssetCheckResult(
        passed=passed,
        description="diagnostic candidate is explicit and cannot grant decision authority",
        metadata={"authority_mode": diagnostic_candidate.get("authority_mode", "")},
    )


@asset_check(
    asset=decision_current,
    name="decision_authority_admission",
    blocking=True,
    compute_kind="boundary_pilot",
)
def decision_authority_admission(decision_current: dict[str, Any]) -> AssetCheckResult:
    passed = (
        decision_current.get("status") == "authorized"
        and decision_current.get("authority_mode") == "ALLOW"
    )
    return AssetCheckResult(
        passed=passed,
        description="decision current requires explicit ALLOW from the promotion gate",
        metadata={"authority_mode": decision_current.get("authority_mode", "")},
    )


BOUNDARY_ASSETS = (
    harvester_release,
    admitted_evidence,
    diagnostic_candidate,
    decision_current,
)
BOUNDARY_CHECKS = (
    harvester_release_admission,
    evidence_integrity,
    diagnostic_authority_boundary,
    decision_authority_admission,
)


__all__ = [
    "BOUNDARY_ASSETS",
    "BOUNDARY_CHECKS",
    "admitted_evidence",
    "build_admitted_evidence",
    "build_decision_current",
    "build_diagnostic_candidate",
    "decision_authority_admission",
    "decision_current",
    "diagnostic_authority_boundary",
    "diagnostic_candidate",
    "evidence_integrity",
    "harvester_release",
    "harvester_release_admission",
    "read_harvester_release",
]
