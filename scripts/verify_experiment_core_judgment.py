#!/usr/bin/env python3
"""Verify that REAL_EXPERIMENTAL module outputs don't leak into core judgment.

Reads governance/capability_registry.yaml for experimental modules, then checks
that Output/current/ and Output/judgment/ don't contain unreviewed references
to experimental module outputs.

Classification system:
  allow_diagnostic  — reference is audit trail / display only, does NOT affect
                      decision, confidence, claim_ceiling, or position.
                      Requires: marker in file, expiry date, affects_core_judgment=false.
  require_bridge    — reference affects explanation, confidence, claim ceiling,
                      or next action.  Must go through bridge/gate before
                      entering core judgment.  Temporary approval with expiry.
  block             — reference affects decision, risk gate, trade decision,
                      or position sizing.  Must be removed from core path.

Unmarked experimental references default to FAIL — no blanket exceptions.

Authority: governance/system_constitution.yaml → hard_authority_rule

Usage:
    python3 scripts/verify_experiment_core_judgment.py
    python3 scripts/verify_experiment_core_judgment.py --json
    python3 scripts/verify_experiment_core_judgment.py --audit   # write audit report

Exit codes:
    0 — no unclassified violations
    1 — unclassified or blocked experimental reference found
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._runtime_io import (  # noqa: E402
    ROOT,
    ensure_dir,
    load_yaml,
    surface_dir,
    write_json,
)

CAPABILITY_REGISTRY = ROOT / "governance" / "capability_registry.yaml"
AUDIT_MD_PATH = surface_dir("system_learning") / "latest" / "experiment_core_judgment_audit.md"


def _audit_report_paths() -> tuple[Path, Path]:
    """Audit report (markdown, JSON) paths, isolated on ephemeral CI runners.

    GitHub Actions runs this check inside a fresh checkout where the
    clean-checkout boundary contract (scripts/commands/ci/clean_checkout_boundary.py)
    forbids materializing ``Output/`` content; reports land in a temporary
    directory there instead of the workspace surface.
    """
    md_path = AUDIT_MD_PATH
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
        md_path = Path(tempfile.mkdtemp(prefix="experiment-core-judgment-audit-")) / AUDIT_MD_PATH.name
    return md_path, md_path.with_suffix(".json")

# Patterns that indicate experimental module output in core judgment paths.
EXPERIMENTAL_INDICATORS = [
    "ml_signals", "ml-signals",
    "backtest_lens", "backtest-lens",
    "qlib_benchmark", "qlib-benchmark", "qlib_benchmark_runner",
    "regime_detection", "factor_model", "graph_embeddings",
    "historical_replay",
]

# Fields that directly affect core judgment decisions → BLOCK.
CORE_DECISION_FIELDS = {
    "decision", "allowed_size", "position", "trade_decision",
    "risk_gate", "position_sizing", "execution",
}

# Fields that affect confidence / claim ceiling / next action → REQUIRE_BRIDGE.
CORE_CONFIDENCE_FIELDS = {
    "confidence", "claim_ceiling", "next_action", "actionability",
    "trade_confidence", "mechanism_confidence",
}

# Fields that are diagnostic / provenance only → ALLOW_DIAGNOSTIC.
DIAGNOSTIC_FIELD_PREFIXES = (
    "inputs.", "signals[", "source", "metadata.", "provenance.",
    "references.", "trace.", "audit.", "generated_at", "schema_version",
)

# Approved diagnostic markers — classified references with expiry dates.
# No permanent exemptions.  All must have expires_at.
# Each entry is (pattern, config) — multiple entries per pattern allowed.
APPROVED_DIAGNOSTIC_MARKERS: list[tuple[str, dict[str, Any]]] = [
    ("Output/current/signal_consensus.json", {
        "indicator": "ml_signals",
        "classification": "allow_diagnostic",
        "reason": (
            "HMM classified as monitoring_only by signal_consensus pipeline; "
            "explicitly does_not_support regime_call/primary_signal/standalone_claim"
        ),
        "affects_core_judgment": False,
        "expires_at": "2026-07-18",
        "review_required": True,
    }),
    ("Output/judgment/*.json", {
        "indicator": "ml_signals",
        "field_pattern": "inputs.hmm",
        "classification": "allow_diagnostic",
        "reason": (
            "File path in inputs section is audit trail only; "
            "does not inject values into judgment logic"
        ),
        "affects_core_judgment": False,
        "expires_at": "2026-07-18",
        "review_required": True,
    }),
    ("Output/quality/*", {
        "indicator": "strategy_lab",
        "classification": "allow_diagnostic",
        "reason": (
            "Quality audit/triage documents are diagnostic refactoring artifacts; "
            "do not affect decision, confidence, or position sizing"
        ),
        "affects_core_judgment": False,
        "expires_at": "2026-12-31",
        "review_required": False,
    }),
    ("Output/quality/*", {
        "indicator": "regime_detection",
        "classification": "allow_diagnostic",
        "reason": (
            "Quality audit/triage documents reference regime_detection as pipeline step; "
            "does not inject experimental values into core judgment"
        ),
        "affects_core_judgment": False,
        "expires_at": "2026-12-31",
        "review_required": False,
    }),
    ("Output/quality/*", {
        "indicator": "ml_signals",
        "classification": "allow_diagnostic",
        "reason": (
            "Quality audit/triage documents reference ML Signals as module name; "
            "does not inject experimental values into core judgment"
        ),
        "affects_core_judgment": False,
        "expires_at": "2026-12-31",
        "review_required": False,
    }),
]


def get_experimental_modules(registry: dict) -> list[str]:
    """Extract module names with status REAL_EXPERIMENTAL."""
    return [
        name for name, entry in registry.items()
        if isinstance(entry, dict) and entry.get("status") == "REAL_EXPERIMENTAL"
    ]


def scan_core_judgment_paths(root: Path) -> list[Path]:
    """Return list of core judgment directories to scan."""
    core_dirs = [
        surface_dir("current") if root == ROOT else root / "Output" / "current",
        surface_dir("judgment") if root == ROOT else root / "Output" / "judgment",
        surface_dir("trade_decision") if root == ROOT else root / "Output" / "trade_decision",
        surface_dir("quality") if root == ROOT else root / "Output" / "quality",
    ]
    return [d for d in core_dirs if d.exists()]


def _find_json_paths(obj: Any, path: str = "") -> list[tuple[str, Any]]:
    """Flatten a JSON object into (dotted_path, value) pairs."""
    pairs: list[tuple[str, Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else k
            pairs.append((p, v))
            pairs.extend(_find_json_paths(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            pairs.append((p, v))
            pairs.extend(_find_json_paths(v, p))
    return pairs


def _classify_field(field_path: str) -> str:
    """Classify field impact: 'decision', 'confidence', or 'diagnostic'."""
    top = field_path.split(".")[0].split("[")[0]
    if top in CORE_DECISION_FIELDS:
        return "decision"
    if top in CORE_CONFIDENCE_FIELDS:
        return "confidence"
    for prefix in DIAGNOSTIC_FIELD_PREFIXES:
        if field_path.startswith(prefix):
            return "diagnostic"
    return "diagnostic"


def _match_approved_marker(filepath: Path, indicator: str, field_path: str) -> dict | None:
    """Check if a reference matches an approved diagnostic marker."""
    relative_candidates: list[str] = []
    try:
        relative_candidates.append(str(filepath.absolute().relative_to(ROOT.absolute())))
    except ValueError:
        pass
    try:
        relative_candidates.append(str(filepath.resolve().relative_to(ROOT.resolve())))
    except ValueError:
        pass
    if not relative_candidates:
        return None
    for pattern, marker in APPROVED_DIAGNOSTIC_MARKERS:
        if marker.get("indicator") != indicator:
            continue
        if not any(fnmatch.fnmatch(rel, pattern) for rel in relative_candidates):
            continue
        fp = marker.get("field_pattern", "")
        if fp and fp not in field_path:
            continue
        return marker
    return None


def _is_expired(marker: dict) -> bool:
    """Check if an approved marker has expired."""
    expires = marker.get("expires_at")
    if not expires:
        return True
    try:
        if "T" not in str(expires):
            return datetime.now(UTC).date() > datetime.fromisoformat(str(expires)).date()
        return datetime.now(UTC) > datetime.fromisoformat(expires).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return True


def classify_reference(
    filepath: Path,
    indicator: str,
    field_path: str,
) -> dict[str, Any]:
    """Classify a single experimental reference by field semantics."""
    impact = _classify_field(field_path)

    # BLOCK: experimental reference in decision/position fields
    if impact == "decision":
        return {
            "classification": "block",
            "decision": "FAIL",
            "reason": f"Experimental '{indicator}' in decision field '{field_path}'",
            "affects_core_judgment": True,
            "required_fix": f"Remove {indicator} from {field_path} or route through authorized gate",
        }

    # Check for approved marker (must not be expired)
    marker = _match_approved_marker(filepath, indicator, field_path)
    if marker:
        if _is_expired(marker):
            return {
                "classification": marker["classification"],
                "decision": "FAIL",
                "reason": f"Approved marker expired on {marker.get('expires_at', 'unknown')}",
                "affects_core_judgment": marker.get("affects_core_judgment", True),
                "required_fix": "Re-review and renew approval or remove reference",
            }
        if marker["classification"] == "allow_diagnostic" and not marker.get("affects_core_judgment"):
            return {
                "classification": "allow_diagnostic",
                "decision": "PASS",
                "reason": marker.get("reason", ""),
                "affects_core_judgment": False,
                "expires_at": marker.get("expires_at"),
            }

    # REQUIRE_BRIDGE: experimental reference in confidence/claim_ceiling fields
    if impact == "confidence":
        return {
            "classification": "require_bridge",
            "decision": "FAIL",
            "reason": f"Experimental '{indicator}' affects confidence field '{field_path}' without marker",
            "affects_core_judgment": True,
            "required_fix": "Add approved diagnostic marker with expiry, or route through bridge/gate",
        }

    # Unmarked reference in diagnostic field — still needs classification
    return {
        "classification": "unknown",
        "decision": "FAIL",
        "reason": f"Experimental '{indicator}' in '{field_path}' without classification",
        "affects_core_judgment": False,
        "required_fix": "Classify as allow_diagnostic/require_bridge/block and add marker",
    }


def verify_core_judgment(root: Path) -> tuple[list[dict], list[dict]]:
    """Run the experiment → core judgment verification.

    Returns: (violations, audit_entries)
    """
    registry = load_yaml(CAPABILITY_REGISTRY)
    if not registry:
        return [{"severity": "ERROR", "message": "Cannot load capability registry"}], []

    experimental = get_experimental_modules(registry)
    all_indicators = list(set(EXPERIMENTAL_INDICATORS + experimental))

    core_dirs = scan_core_judgment_paths(root)
    violations: list[dict] = []
    audit_entries: list[dict] = []

    for core_dir in core_dirs:
        for filepath in sorted(core_dir.rglob("*")):
            if not filepath.is_file() or filepath.is_symlink():
                continue
            if filepath.suffix in (".png", ".jpg", ".gif", ".ico", ".bin", ".dat", ".db"):
                continue
            try:
                if filepath.stat().st_size > 5_000_000:
                    continue
            except OSError:
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            rel_path = str(filepath.relative_to(root))

            for indicator in all_indicators:
                if indicator.lower() not in content.lower():
                    continue

                if filepath.suffix == ".json":
                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError:
                        continue
                    for field_path, value in _find_json_paths(data):
                        if not isinstance(value, str) or indicator.lower() not in value.lower():
                            continue
                        cls = classify_reference(filepath, indicator, field_path)
                        entry = {
                            "file": rel_path,
                            "field": field_path,
                            "source_module": indicator,
                            "value": value[:200],
                            **cls,
                        }
                        audit_entries.append(entry)
                        if cls["decision"] in ("FAIL",):
                            violations.append({
                                "severity": "FAIL",
                                "file": rel_path,
                                "field": field_path,
                                "experimental_reference": indicator,
                                "classification": cls["classification"],
                                "message": f"[{cls['classification'].upper()}] {rel_path}:{field_path} — {cls['reason']}",
                            })
                else:
                    # Non-JSON: string match with context
                    for match in re.finditer(re.escape(indicator), content, re.IGNORECASE):
                        ctx_start = max(0, match.start() - 40)
                        ctx_end = min(len(content), match.end() + 40)
                        context = content[ctx_start:ctx_end].replace("\n", " ")
                        cls = classify_reference(filepath, indicator, context[:80])
                        entry = {
                            "file": rel_path,
                            "field": context[:80],
                            "source_module": indicator,
                            **cls,
                        }
                        audit_entries.append(entry)
                        if cls["decision"] in ("FAIL",):
                            violations.append({
                                "severity": "FAIL",
                                "file": rel_path,
                                "experimental_reference": indicator,
                                "classification": cls["classification"],
                                "message": f"[{cls['classification'].upper()}] {rel_path} — {cls['reason']}",
                            })

    return violations, audit_entries


def write_audit_report(audit_entries: list[dict], violations: list[dict]) -> None:
    """Write the classification audit report to Output/system_learning/latest/."""
    audit_md_path, audit_json_path = _audit_report_paths()
    ensure_dir(audit_md_path.parent)
    now = datetime.now(UTC).isoformat()

    summary = {
        "total_references": len(audit_entries),
        "allow_diagnostic": sum(1 for e in audit_entries if e.get("classification") == "allow_diagnostic"),
        "require_bridge": sum(1 for e in audit_entries if e.get("classification") == "require_bridge"),
        "block": sum(1 for e in audit_entries if e.get("classification") == "block"),
        "unknown": sum(1 for e in audit_entries if e.get("classification") == "unknown"),
    }

    lines = [
        "# Experiment → Core Judgment Audit",
        "",
        f"**Generated:** {now}",
        "",
        "## Summary",
        "",
        f"- Total references: {summary['total_references']}",
        f"- **allow_diagnostic**: {summary['allow_diagnostic']}",
        f"- **require_bridge**: {summary['require_bridge']}",
        f"- **block**: {summary['block']}",
        f"- **unknown**: {summary['unknown']}",
        "",
        "## Classification Rules",
        "",
        "| Classification | Meaning | Required Marker |",
        "|---|---|---|",
        "| `allow_diagnostic` | Audit trail / display only, no judgment impact | `diagnostic_only`, `affects_core_judgment: false`, expiry date |",
        "| `require_bridge` | Affects confidence/claim_ceiling/next_action | Must go through bridge/gate, expiry date |",
        "| `block` | Affects decision/risk_gate/trade/position | Must be removed from core path |",
        "",
        "## Entries",
        "",
    ]

    for entry in audit_entries:
        decision = str(entry.get("decision", ""))
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(decision, "?")
        lines.append(f"### {icon} `{entry.get('file', '?')}` → `{entry.get('field', '?')}`")
        lines.append(f"- **Source:** `{entry.get('source_module', '?')}`")
        lines.append(f"- **Value:** `{entry.get('value', '?')[:120]}`")
        lines.append(f"- **Classification:** `{entry.get('classification', '?')}`")
        lines.append(f"- **Decision:** {entry.get('decision', '?')}")
        lines.append(f"- **Reason:** {entry.get('reason', '?')}")
        lines.append(f"- **Affects core judgment:** {entry.get('affects_core_judgment', '?')}")
        if entry.get("expires_at"):
            lines.append(f"- **Expires:** {entry['expires_at']}")
        if entry.get("required_fix"):
            lines.append(f"- **Required fix:** {entry['required_fix']}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "*Generated by scripts/verify_experiment_core_judgment.py*",
        "*Authority: governance/system_constitution.yaml → hard_authority_rule*",
    ])

    audit_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Also write JSON
    write_json(audit_json_path, {
        "schema_version": "experiment_core_judgment_audit.v1",
        "generated_at": now,
        "summary": summary,
        "entries": audit_entries,
        "violations": violations,
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("--audit", action="store_true", help="Write audit report to Output/.")
    args = parser.parse_args()

    violations, audit_entries = verify_core_judgment(ROOT)

    # Always write audit report
    write_audit_report(audit_entries, violations)

    if args.json:
        report = {
            "check": "experiment_core_judgment",
            "violations": violations,
            "audit_entries": audit_entries,
            "status": "FAIL" if any(v["severity"] == "FAIL" for v in violations) else "PASS",
        }
        print(json.dumps(report, indent=2))
    else:
        if violations:
            fails = [v for v in violations if v["severity"] == "FAIL"]
            warns = [v for v in violations if v["severity"] == "WARN"]
            if fails:
                print(f"FAIL: {len(fails)} unclassified/blocked experimental reference(s):")
                for v in fails:
                    print(f"  {v['message']}")
            if warns:
                print(f"WARN: {len(warns)} bridge-required reference(s):")
                for v in warns:
                    print(f"  {v['message']}")
        summary = {
            "allow_diagnostic": sum(1 for e in audit_entries if e.get("classification") == "allow_diagnostic"),
            "require_bridge": sum(1 for e in audit_entries if e.get("classification") == "require_bridge"),
            "block": sum(1 for e in audit_entries if e.get("classification") == "block"),
            "unknown": sum(1 for e in audit_entries if e.get("classification") == "unknown"),
        }
        if violations:
            print(f"\nClassification: {json.dumps(summary)}")
            print(f"Audit report: {AUDIT_MD_PATH}")

    # Fail only on unclassified or blocked references
    has_violation = any(
        v["severity"] == "FAIL" and v.get("classification") in ("unknown", "block")
        for v in violations
    )
    return 1 if has_violation else 0


if __name__ == "__main__":
    sys.exit(main())
