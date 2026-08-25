"""Build data gaps — extract unmet data needs and generate Harvester request candidates.

Reads current artifacts and produces data_gaps.md and data_gaps.json
that identify what data is missing, what judgment it affects, and how
fixing it would improve the system.

Each gap now generates a structured request candidate that Harvester can
process. Modules don't search for data themselves — they submit needs
through this system.

Usage:
    python3 scripts/commands/weekly/build_data_gaps.py
    python3 scripts/commands/weekly/build_data_gaps.py --json
    python3 scripts/commands/weekly/build_data_gaps.py --write-requests   # sync candidates to registry
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment,misc]

from scripts._runtime_io import ROOT, current_dir, ensure_dir, surface_dir  # noqa: E402
from scripts._runtime_io import load_json as _load_json
from scripts._runtime_io import load_yaml as _load_yaml

logger = logging.getLogger(__name__)

CURRENT = current_dir()
JUDGMENT = surface_dir("judgment")
DATA_AUTHORITY_PATH = ROOT / "governance" / "authority_registry.yaml"
DATA_REQUEST_PATH = ROOT / "governance" / "data_request_registry.yaml"


# ---------------------------------------------------------------------------
# Gap → request candidate mapping
# ---------------------------------------------------------------------------

# Canonical mapping: gap_id → request candidate template.
# Fields: requested_by, needed_for, data_needed, current_source,
#         current_authority, non_harvester_flag, priority mapping.
_GAP_REQUEST_MAP: dict[str, dict[str, Any]] = {
    "hmm_training_data": {
        "request_id": "hmm_training_data",
        "requested_by": "ML Signals",
        "needed_for": "HMM stability — regime detection confidence",
        "data_needed": "252+ days of benchmark OHLCV via Harvester",
        "current_source": "Data/harvester/exports/latest/data/benchmark_panel.parquet",
        "current_authority": "harvester",
        "non_harvester_flag": False,
        "priority": "high",
    },
    "claim_ceiling_lift": {
        "request_id": "claim_ceiling_lift",
        "requested_by": "Workbench",
        "needed_for": "Claim ceiling — operational decision capability",
        "data_needed": "Governance approval, not a data acquisition task",
        "current_source": "N/A (governance gate)",
        "current_authority": "N/A",
        "non_harvester_flag": False,
        "priority": "high",
    },
    "K_measurement_quality": {
        "request_id": "K_measurement_quality",
        "requested_by": "Workbench",
        "needed_for": "K channel authority and K/X gate passage",
        "data_needed": "Higher quality K curvature signals from Harvester",
        "current_source": "Data/harvester/exports/latest/",
        "current_authority": "harvester",
        "non_harvester_flag": False,
        "priority": "medium",
    },
    "X_agg_measurement_quality": {
        "request_id": "X_agg_measurement_quality",
        "requested_by": "Workbench",
        "needed_for": "X_agg channel authority and K/X gate passage",
        "data_needed": "Higher quality X aggregate signals from Harvester",
        "current_source": "Data/harvester/exports/latest/",
        "current_authority": "harvester",
        "non_harvester_flag": False,
        "priority": "medium",
    },
    "cross_asset_confirmation": {
        "request_id": "cross_asset_confirmation",
        "requested_by": "Workbench Signals",
        "needed_for": "K channel — cross-asset curvature family",
        "data_needed": "SPY/TLT/HYG/GLD daily panel via Harvester",
        "current_source": "Data/harvester/exports/latest/data/cross_asset_daily_panel.parquet",
        "current_authority": "harvester",
        "non_harvester_flag": False,
        "priority": "medium",
    },
}


def _build_request_candidate(gap: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a gap into a structured Harvester request candidate.

    Returns None if the gap doesn't map to a data request (e.g. governance gates).
    """
    gap_id = gap.get("gap_id", "")
    template = _GAP_REQUEST_MAP.get(gap_id)
    if not template:
        return None

    # Determine core_judgment_allowed based on authority.
    authority = template.get("current_authority", "")
    non_harvester = template.get("non_harvester_flag", False)
    if non_harvester:
        core_judgment_allowed = False
    elif authority == "harvester":
        core_judgment_allowed = True
    else:
        core_judgment_allowed = False

    return {
        "request_id": template["request_id"],
        "requested_by": template["requested_by"],
        "needed_for": template["needed_for"],
        "data_needed": template["data_needed"],
        "current_source": template["current_source"],
        "current_authority": authority,
        "non_harvester_flag": non_harvester,
        "core_judgment_allowed": core_judgment_allowed,
        "priority": template["priority"],
        "status": "pending",
        "gap_id": gap_id,
        "created": datetime.now(UTC).strftime("%Y-%m-%d"),
    }


def _extract_gaps_from_judgment(judgment: dict, fw: dict) -> list[dict[str, Any]]:
    """Extract data gaps from judgment confidence reasons and gate status."""
    gaps = []

    conf = judgment.get("confidence", {})
    reasons = conf.get("reasons", []) if isinstance(conf, dict) else []
    gate_status = judgment.get("gate_status", {})

    # HMM stability gaps
    if gate_status.get("hmm_stability") in ("WEAK", "BLOCKED"):
        hmm_reasons = [r for r in reasons if "hmm" in r.lower() or "sample" in r.lower()]
        gaps.append({
            "gap_id": "hmm_training_data",
            "description": "HMM needs longer training window (252+ days)",
            "affected_judgment": "HMM stability → regime detection confidence",
            "current_state": gate_status.get("hmm_stability", "UNKNOWN"),
            "improvement_if_fixed": "HMM could reach ADEQUATE, improving confidence",
            "priority": "high",
            "type": "training_data",
            "details": hmm_reasons[:2] if hmm_reasons else [],
        })

    # Channel coverage gaps
    if fw:
        adv = fw.get("advanced", {})
        coverage = adv.get("channel_coverage", {})
        not_implemented = coverage.get("channels_not_implemented", [])
        if not_implemented:
            gaps.append({
                "gap_id": "missing_channels",
                "description": f"Channels not implemented: {', '.join(not_implemented)}",
                "affected_judgment": "Measurement completeness and claim ceiling",
                "current_state": f"{len(not_implemented)} channels missing",
                "improvement_if_fixed": "Full M/D/K/X coverage → higher claim ceiling",
                "priority": "high",
                "type": "proxy_coverage",
                "details": not_implemented,
            })

        # K/X measurement quality
        channel_conf = adv.get("channel_confidence", {})
        for ch in ["K", "X_agg"]:
            conf_entry = channel_conf.get(ch, {})
            if conf_entry.get("confidence") in ("weak", "very_weak", "low"):
                gaps.append({
                    "gap_id": f"{ch}_measurement_quality",
                    "description": f"{ch} measurement quality is {conf_entry.get('confidence', 'unknown')}",
                    "affected_judgment": f"{ch} channel authority and K/X gate passage",
                    "current_state": f"{ch} confidence = {conf_entry.get('confidence', 'unknown')}",
                    "improvement_if_fixed": f"{ch} could contribute to primary readout",
                    "priority": "medium",
                    "type": "measurement_quality",
                    "details": [conf_entry.get("note", "")] if conf_entry.get("note") else [],
                })

    # Claim ceiling gap
    claim = judgment.get("claim_ceiling", "")
    if "diagnostic" in claim.lower():
        gaps.append({
            "gap_id": "claim_ceiling_lift",
            "description": "Claim ceiling is diagnostic — cannot make operational decisions",
            "affected_judgment": "All trade decisions capped at WATCH",
            "current_state": f"Claim ceiling = {claim}",
            "improvement_if_fixed": "System could make HEDGE/TACTICAL decisions",
            "priority": "high",
            "type": "governance",
            "details": [],
        })

    # Cross-asset confirmation gap
    gaps.append({
        "gap_id": "cross_asset_confirmation",
        "description": "Cross-asset ETF panel for K cross-asset curvature confirmation",
        "affected_judgment": "K channel — cross-asset curvature family",
        "current_state": "Not in Harvester; using synthetic/missing",
        "improvement_if_fixed": "K could use SPY/TLT/HYG/GLD curvature for confirmation",
        "priority": "medium",
        "type": "harvester_request",
        "details": ["Need Harvester release with cross-asset daily panel"],
    })

    return gaps


# ---------------------------------------------------------------------------
# Existing request registry reading (fixed)
# ---------------------------------------------------------------------------

def _check_existing_requests(data_request_path: Path | None = None) -> list[dict[str, Any]]:
    """Check what data requests already exist in the registry."""
    reg = _load_yaml(data_request_path or DATA_REQUEST_PATH)
    if not reg:
        return []

    requests = []
    for item in reg.get("requests", []):
        # Use explicit flag if present; otherwise infer from authority
        if "non_harvester_flag" in item:
            nh = item["non_harvester_flag"]
        else:
            auth = item.get("current_authority", "")
            nh = auth not in ("harvester", "N/A", "")
        requests.append({
            "request_id": item.get("request_id", "unknown"),
            "status": item.get("status", "unknown"),
            "requested_by": item.get("requested_by", "unknown"),
            "needed_for": item.get("needed_for", "")[:100],
            "priority": item.get("priority", "unknown"),
            "non_harvester_flag": nh,
            "core_judgment_priority": item.get("core_judgment_priority", "unknown"),
        })
    return requests


def _match_gaps_to_requests(
    gaps: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Match gaps to existing registry requests; flag unmatched gaps."""
    existing_ids = {r["request_id"] for r in existing}
    matched = []
    for gap in gaps:
        gap_id = gap.get("gap_id", "")
        if gap_id in existing_ids:
            matched.append({
                "gap_id": gap_id,
                "registry_status": "registered",
                "request_id": gap_id,
            })
        else:
            matched.append({
                "gap_id": gap_id,
                "registry_status": "not_registered",
                "request_id": None,
            })
    return matched


# ---------------------------------------------------------------------------
# Data authority gap checking
# ---------------------------------------------------------------------------

def _check_data_authority_gaps(data_authority_path: Path | None = None) -> list[dict[str, str]]:
    """Check authority_registry for data sources needing Harvester migration."""
    reg = _load_yaml(data_authority_path or DATA_AUTHORITY_PATH)
    if not reg:
        return []

    gaps = []
    for entry in reg.get("data_sources", []):
        auth = entry.get("authority", "")
        if auth == "non_harvester_transitional":
            gaps.append({
                "path": entry.get("path", "unknown"),
                "authority": auth,
                "note": entry.get("note", "")[:100],
                "action": "Migrate to Harvester or mark research_only",
                "data_request_id": entry.get("data_request_id", ""),
                "allowed_use": entry.get("allowed_use", []),
                "forbidden_use": entry.get("forbidden_use", []),
            })
    return gaps


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build_data_gaps(
    *,
    current_path: Path | None = None,
    judgment_path: Path | None = None,
    data_authority_path: Path | None = None,
    data_request_path: Path | None = None,
) -> dict[str, Any]:
    """Build the complete data gaps report with request candidates.

    The optional paths are an explicit execution boundary for Dagster native
    assets.  The no-argument compatibility callable resolves the same default
    surfaces at call time, so a generation candidate selected after module
    import is still honored.
    """
    current = current_path or current_dir()
    judgment_dir = judgment_path or surface_dir("judgment")
    judgment = _load_json(judgment_dir / "latest.json")
    fw = _load_json(current / "framework_output.json")

    if not judgment:
        return {
            "schema_version": "data_gaps.v2",
            "generated_at": datetime.now(UTC).isoformat(),
            "error": "No judgment artifact found",
            "gaps": [],
            "request_candidates": [],
        }

    gaps = _extract_gaps_from_judgment(judgment, fw)

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    gaps.sort(key=lambda g: priority_order.get(g.get("priority", "low"), 9))

    # Generate request candidates from gaps
    request_candidates = []
    for gap in gaps:
        candidate = _build_request_candidate(gap)
        if candidate:
            request_candidates.append(candidate)

    existing_requests = _check_existing_requests(data_request_path)
    gap_request_matches = _match_gaps_to_requests(gaps, existing_requests)

    # Count non-harvester flags
    non_harvester_count = sum(1 for c in request_candidates if c.get("non_harvester_flag"))
    blocked_from_judgment = sum(
        1 for c in request_candidates if not c.get("core_judgment_allowed")
    )

    return {
        "schema_version": "data_gaps.v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "gaps": gaps,
        "request_candidates": request_candidates,
        "existing_requests": existing_requests,
        "gap_request_matches": gap_request_matches,
        "authority_gaps": _check_data_authority_gaps(data_authority_path),
        "summary": {
            "total_gaps": len(gaps),
            "high_priority": sum(1 for g in gaps if g.get("priority") == "high"),
            "medium_priority": sum(1 for g in gaps if g.get("priority") == "medium"),
            "total_request_candidates": len(request_candidates),
            "non_harvester_data_count": non_harvester_count,
            "blocked_from_core_judgment": blocked_from_judgment,
        },
    }


# ---------------------------------------------------------------------------
# Request candidate → registry sync
# ---------------------------------------------------------------------------

def write_request_candidates_to_registry(
    report: dict[str, Any],
    *,
    data_request_path: Path | None = None,
) -> int:
    """Write new request candidates into data_request_registry.yaml.

    Only adds candidates whose request_id is not already in the registry.
    Returns the number of new requests added.
    """
    if yaml is None:
        logger.warning("pyyaml not installed; cannot write registry")
        return 0

    request_path = data_request_path or DATA_REQUEST_PATH
    reg = _load_yaml(request_path)
    if not reg:
        reg = {
            "schema_version": "data_request.v1",
            "created": datetime.now(UTC).strftime("%Y-%m-%d"),
            "purpose": (
                "Modules request data from Harvester through this registry. "
                "Harvester aggregates, prioritizes, and responds. "
                "No module should permanently bypass Harvester with direct acquisition."
            ),
            "requests": [],
        }

    existing_ids = {r.get("request_id") for r in reg.get("requests", [])}
    candidates = report.get("request_candidates", [])
    new_count = 0

    for candidate in candidates:
        req_id = candidate.get("request_id", "")
        if req_id in existing_ids:
            continue

        new_entry = {
            "request_id": req_id,
            "requested_by": candidate.get("requested_by", "unknown"),
            "needed_for": candidate.get("needed_for", ""),
            "data_needed": candidate.get("data_needed", ""),
            "current_source": candidate.get("current_source", ""),
            "current_authority": candidate.get("current_authority", "unknown"),
            "non_harvester_flag": candidate.get("non_harvester_flag", False),
            "core_judgment_allowed": candidate.get("core_judgment_allowed", False),
            "status": "pending",
            "priority": candidate.get("priority", "medium"),
            "harvester_response": "pending",
            "core_judgment_priority": (
                "blocked_until_harvester" if not candidate.get("core_judgment_allowed")
                else "normal"
            ),
            "created": candidate.get("created", datetime.now(UTC).strftime("%Y-%m-%d")),
        }
        reg.setdefault("requests", []).append(new_entry)
        new_count += 1

    if new_count > 0:
        # Update timestamp
        reg["updated_at"] = datetime.now(UTC).strftime("%Y-%m-%d")
        request_path.write_text(
            yaml.dump(reg, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    return new_count


# ---------------------------------------------------------------------------
# Markdown generation
# ---------------------------------------------------------------------------

def generate_markdown(report: dict[str, Any]) -> str:
    """Generate markdown data gaps report with request candidates."""
    if report.get("error"):
        return f"# Data Gaps\n\n**Error:** {report['error']}\n"

    s = report["summary"]
    lines = [
        f"# Data Gaps — {report['generated_at'][:10]}",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Total gaps:** {s['total_gaps']} (high: {s['high_priority']}, medium: {s['medium_priority']})",
        f"**Request candidates:** {s['total_request_candidates']} "
        f"(non-Harvester: {s['non_harvester_data_count']}, "
        f"blocked from core judgment: {s['blocked_from_core_judgment']})",
        "",
        "---",
        "",
    ]

    # High priority gaps
    high = [g for g in report["gaps"] if g.get("priority") == "high"]
    if high:
        lines.append("## 🔴 High Priority Gaps")
        lines.append("")
        for gap in high:
            lines.append(f"### {gap['gap_id']}")
            lines.append("")
            lines.append(f"- **Description:** {gap['description']}")
            lines.append(f"- **Affects:** {gap['affected_judgment']}")
            lines.append(f"- **Current:** {gap['current_state']}")
            lines.append(f"- **If fixed:** {gap['improvement_if_fixed']}")
            if gap.get("details"):
                for d in gap["details"]:
                    lines.append(f"  - {d}")
            lines.append("")

    # Medium priority gaps
    medium = [g for g in report["gaps"] if g.get("priority") == "medium"]
    if medium:
        lines.append("## 🟡 Medium Priority Gaps")
        lines.append("")
        for gap in medium:
            lines.append(f"### {gap['gap_id']}")
            lines.append("")
            lines.append(f"- **Description:** {gap['description']}")
            lines.append(f"- **Affects:** {gap['affected_judgment']}")
            lines.append(f"- **Current:** {gap['current_state']}")
            lines.append(f"- **If fixed:** {gap['improvement_if_fixed']}")
            lines.append("")

    # --- Request candidates section ---
    candidates = report.get("request_candidates", [])
    if candidates:
        lines += [
            "---",
            "",
            "## 📋 Harvester Request Candidates",
            "",
            "These are structured requests generated from gaps. "
            "Modules submit needs here — Harvester aggregates and responds.",
            "",
        ]
        for c in candidates:
            nh_flag = " ⚠️ **NON-HARVESTER**" if c.get("non_harvester_flag") else ""
            core_tag = "✅ allowed" if c.get("core_judgment_allowed") else "🚫 blocked"
            lines.append(f"### {c['request_id']}{nh_flag}")
            lines.append("")
            lines.append(f"- **Requested by:** {c['requested_by']}")
            lines.append(f"- **Needed for:** {c['needed_for']}")
            lines.append(f"- **Data needed:** {c['data_needed']}")
            lines.append(f"- **Current source:** `{c['current_source']}`")
            lines.append(f"- **Current authority:** {c['current_authority']}")
            lines.append(f"- **Core judgment:** {core_tag}")
            lines.append(f"- **Priority:** {c['priority']}")
            lines.append(f"- **Status:** {c['status']}")
            lines.append("")

    # --- Gap → registry alignment ---
    matches = report.get("gap_request_matches", [])
    not_registered = [m for m in matches if m["registry_status"] == "not_registered"]
    if not_registered:
        lines += [
            "---",
            "",
            "## ⚡ Gaps Not Yet in Request Registry",
            "",
            "These gaps have no formal request entry. "
            "Run `--write-requests` to sync them into the registry.",
            "",
        ]
        for m in not_registered:
            lines.append(f"- `{m['gap_id']}` → needs registry entry")
        lines.append("")

    # --- Existing requests ---
    existing = report.get("existing_requests", [])
    if existing:
        lines += [
            "---",
            "",
            "## Existing Data Requests (from registry)",
            "",
        ]
        for req in existing:
            nh_marker = " [non-Harvester]" if req.get("non_harvester_flag") else ""
            lines.append(
                f"- `{req['request_id']}` [{req['status']}] "
                f"({req['priority']}){nh_marker} — {req['needed_for']}"
            )
        lines.append("")

    # --- Authority gaps ---
    authority_gaps = report.get("authority_gaps", [])
    if authority_gaps:
        lines += [
            "---",
            "",
            "## Data Authority Gaps (non-Harvester transitional)",
            "",
        ]
        for ag in authority_gaps:
            allowed = ", ".join(ag.get("allowed_use", []))
            forbidden = ", ".join(ag.get("forbidden_use", []))
            lines.append(f"- `{ag['path']}`")
            lines.append(f"  - Authority: {ag['authority']}")
            lines.append(f"  - Allowed: {allowed}")
            lines.append(f"  - Forbidden: {forbidden}")
            lines.append(f"  - Action: {ag['action']}")
            if ag.get("data_request_id"):
                lines.append(f"  - Linked request: `{ag['data_request_id']}`")
            lines.append("")

    # --- Non-Harvester data policy ---
    if s.get("non_harvester_data_count", 0) > 0:
        lines += [
            "---",
            "",
            "## ⚠️ Non-Harvester Data Policy",
            "",
            "Transitional non-Harvester data is **allowed but restricted**:",
            "",
            "- **Priority:** Low — never overrides Harvester data",
            "- **Tagging:** All non-Harvester usage must be marked in output",
            "- **Core judgment:** Blocked until Harvester release available",
            "- **Research/training:** Permitted with authority tag",
            "",
            "Modules must not permanently depend on non-Harvester sources.",
            "",
        ]

    lines += [
        "---",
        "",
        "*Generated by scripts/commands/weekly/build_data_gaps.py*",
        "*Authority: judgment_layer + framework_output + data_authority_registry + data_request_registry*",
    ]

    return "\n".join(lines) + "\n"


def write_data_gaps_files(
    report: dict[str, Any],
    *,
    current_path: Path | None = None,
) -> tuple[Path, Path]:
    """Write the two declared current-surface artifacts and return their paths."""
    current = current_path or current_dir()
    ensure_dir(current)
    json_path = current / "data_gaps.json"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path = current / "data_gaps.md"
    md_path.write_text(generate_markdown(report), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="Build data gaps report")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--write-requests",
        action="store_true",
        help="Sync request candidates into data_request_registry.yaml",
    )
    args = parser.parse_args()

    report = build_data_gaps()
    write_data_gaps_files(report)

    if args.write_requests:
        n = write_request_candidates_to_registry(report)
        if n > 0:
            logger.info("Synced %d new request(s) to %s", n, DATA_REQUEST_PATH)
        else:
            logger.info("No new requests to sync (all candidates already in registry)")

    if args.json:
        # CLI output — keep as print for piping
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(generate_markdown(report))


if __name__ == "__main__":
    main()
