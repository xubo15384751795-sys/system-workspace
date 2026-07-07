"""Governance audit guards.

Read-only checks that enforce governance memory: contaminated, frozen,
missing-artifact, and diagnostic-only entities must not leak back onto the live
daily surface. The guards never mutate signals, configs, or registries — they
record findings and fail the audit (non-zero exit) on block-severity findings.

The four MVP guards:
  G1 registry_integrity   — registry self-consistency (known status, block terms).
  G2 artifact_reality     — entity that claims active status but its artifact is missing.
  G3 forbidden_reference  — block_in_daily entity referenced on the live daily surface.
  G4 stale_artifact       — canonical daily artifact older than its freshness threshold.
  G5 daily_readout_contract — prevent M/D-primary readout regressions.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .registry import DEFAULT_REGISTRY_RELPATH, Registry, load_registry

SEVERITY_BLOCK = "block"
SEVERITY_WARN = "warn"

FRAMEWORK_OUTPUT_RELPATH = "Output/current/framework_output.json"
PRACTICALITY_DIR_RELPATH = "Output/practicality_trial"
REPORT_DIR_RELPATH = "Output/system_learning/governance_audit"

# Registry-derived governance text is bracketed by these markers in the daily
# note. It documents blocked entities + reactivation paths, so re-scanning it
# with the forbidden_reference guard would be circular; strip it before scanning.
_GOVERNANCE_REGION = re.compile(
    r"<!--\s*GOVERNANCE_POSTURE_START\s*-->.*?<!--\s*GOVERNANCE_POSTURE_END\s*-->",
    re.DOTALL,
)


def strip_governance_regions(text: str) -> str:
    return _GOVERNANCE_REGION.sub("", text)

# Freshness threshold (hours) for the canonical daily artifact.
FRAMEWORK_STALE_HOURS = 24.0


@dataclass(frozen=True)
class Finding:
    guard: str
    severity: str
    entity: str
    detail: str


@dataclass
class AuditReport:
    generated_at: str
    registry_path: str
    ok: bool
    passed_guards: list[str] = field(default_factory=list)
    failed_guards: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    daily_corpus_sources: list[str] = field(default_factory=list)

    def blocked_references(self) -> list[Finding]:
        return [f for f in self.findings if f.guard == "forbidden_reference"]

    def state_mismatches(self) -> list[Finding]:
        return [f for f in self.findings if f.guard == "artifact_reality"]

    def stale_artifacts(self) -> list[Finding]:
        return [f for f in self.findings if f.guard == "stale_artifact"]


# --- Guards -----------------------------------------------------------------


def guard_registry_integrity(registry: Registry) -> list[Finding]:
    findings: list[Finding] = []
    for e in registry.entities:
        if not registry.known_status(e.kind, e.status):
            findings.append(
                Finding(
                    "registry_integrity",
                    SEVERITY_WARN,
                    e.name,
                    f"unknown {e.kind} status '{e.status}'",
                )
            )
        if e.block_in_daily and not any(t.strip() for t in e.reference_terms()):
            findings.append(
                Finding(
                    "registry_integrity",
                    SEVERITY_BLOCK,
                    e.name,
                    "block_in_daily set but no name/alias to match against",
                )
            )
    return findings


def guard_artifact_reality(registry: Registry, system_root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for e in registry.entities:
        if e.status not in registry.active_claiming_statuses:
            continue
        if not e.expect_artifact:
            continue
        artifact = system_root / e.expect_artifact
        missing = not artifact.exists()
        empty = artifact.exists() and artifact.is_file() and artifact.stat().st_size == 0
        if missing or empty:
            findings.append(
                Finding(
                    "artifact_reality",
                    SEVERITY_BLOCK,
                    e.name,
                    f"REALITY_MISMATCH: status '{e.status}' claims active but artifact "
                    f"{'missing' if missing else 'empty'}: {e.expect_artifact}",
                )
            )
    return findings


def guard_forbidden_reference(registry: Registry, daily_corpus: str) -> list[Finding]:
    findings: list[Finding] = []
    corpus = daily_corpus.lower()
    for e in registry.entities:
        if not e.block_in_daily:
            continue
        for term in e.reference_terms():
            term = term.strip()
            if term and term.lower() in corpus:
                findings.append(
                    Finding(
                        "forbidden_reference",
                        SEVERITY_BLOCK,
                        e.name,
                        f"BLOCKED: '{term}' appears on the live daily surface "
                        f"(status '{e.status}'): {e.reason}",
                    )
                )
                break
    return findings


def guard_stale_artifact(system_root: Path, now: datetime) -> list[Finding]:
    fw = system_root / FRAMEWORK_OUTPUT_RELPATH
    if not fw.exists():
        return [Finding("stale_artifact", SEVERITY_BLOCK, FRAMEWORK_OUTPUT_RELPATH, "MISSING: framework_output.json")]
    mtime = datetime.fromtimestamp(fw.stat().st_mtime, tz=UTC)
    age_h = (now - mtime).total_seconds() / 3600
    if age_h > FRAMEWORK_STALE_HOURS:
        return [
            Finding(
                "stale_artifact",
                SEVERITY_WARN,
                FRAMEWORK_OUTPUT_RELPATH,
                f"STALE: framework_output is {age_h:.1f}h old (>{FRAMEWORK_STALE_HOURS:.0f}h)",
            )
        ]
    return []


def _is_negated_contract_line(line: str) -> bool:
    lowered = line.lower()
    negations = (
        "not ",
        "do not",
        "must not",
        "cannot",
        "blocked",
        "disabled",
        "decommission",
        "diagnostic only",
        "diagnostic-only",
        "legacy diagnostic",
        "background-only",
        "not valid for",
        "no primary",
    )
    return any(term in lowered for term in negations)


def guard_daily_readout_contract(daily_corpus: str) -> list[Finding]:
    """Block regressions against the M/D-primary daily readout contract."""
    findings: list[Finding] = []
    for raw_line in daily_corpus.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not line or _is_negated_contract_line(line):
            continue

        if "cofire_count" in lowered and any(
            term in lowered for term in ("primary executive", "primary daily", "primary state", "daily state")
        ):
            findings.append(
                Finding(
                    "daily_readout_contract",
                    SEVERITY_BLOCK,
                    "cofire_count",
                    "cofire_count must remain a legacy diagnostic, not primary executive state.",
                )
            )

        if "dominant_channel" in lowered and any(
            term in lowered for term in ("primary executive", "primary daily", "primary state", "daily state")
        ):
            findings.append(
                Finding(
                    "daily_readout_contract",
                    SEVERITY_BLOCK,
                    "dominant_channel",
                    "dominant_channel must remain a legacy diagnostic, not primary executive state.",
                )
            )

        if "x_agg" in lowered and "daily trigger" in lowered and any(
            term in lowered for term in ("enabled", "restored", "reactivated", "allowed", "active", "fired")
        ):
            findings.append(
                Finding(
                    "daily_readout_contract",
                    SEVERITY_BLOCK,
                    "X_agg",
                    "X_agg daily trigger remains disabled until measurement/discrimination gates pass.",
                )
            )

        kx_reference = "k/x" in lowered or (" k " in f" {lowered} " and "x_agg" in lowered)
        if kx_reference and any(term in lowered for term in ("removed", "deleted", "replaced")) and any(
            term in lowered for term in ("framework", "canonical", "sigmavector", "sigma vector")
        ):
            findings.append(
                Finding(
                    "daily_readout_contract",
                    SEVERITY_BLOCK,
                    "K/X",
                    "K and X_agg must remain canonical dimensions; only their daily readout role is downgraded.",
                )
            )

    return findings


# --- Corpus + orchestration -------------------------------------------------


def build_daily_corpus(system_root: Path) -> tuple[str, list[str]]:
    """Concatenate the canonical daily surface the guards scan for forbidden refs."""
    parts: list[str] = []
    sources: list[str] = []

    fw = system_root / FRAMEWORK_OUTPUT_RELPATH
    if fw.exists():
        parts.append(fw.read_text(encoding="utf-8"))
        sources.append(FRAMEWORK_OUTPUT_RELPATH)

    note_dir = system_root / PRACTICALITY_DIR_RELPATH
    if note_dir.exists():
        # Only the canonical daily note (YYYY-MM-DD_daily_note.md), not audit
        # reports that legitimately document blocked entities.
        notes = sorted(note_dir.glob("*_daily_note.md"))
        if notes:
            latest = notes[-1]
            parts.append(strip_governance_regions(latest.read_text(encoding="utf-8")))
            sources.append(str(latest.relative_to(system_root)))

    return "\n".join(parts), sources


def run_governance_audit(
    system_root: Path,
    *,
    registry: Registry | None = None,
    registry_path: Path | None = None,
    daily_corpus: str | None = None,
    now: datetime | None = None,
) -> AuditReport:
    system_root = Path(system_root)
    now = now or datetime.now(UTC)
    reg_path = registry_path or (system_root / DEFAULT_REGISTRY_RELPATH)
    if registry is None:
        registry = load_registry(reg_path)

    sources: list[str] = []
    if daily_corpus is None:
        daily_corpus, sources = build_daily_corpus(system_root)

    guard_results = {
        "registry_integrity": guard_registry_integrity(registry),
        "artifact_reality": guard_artifact_reality(registry, system_root),
        "forbidden_reference": guard_forbidden_reference(registry, daily_corpus),
        "stale_artifact": guard_stale_artifact(system_root, now),
        "daily_readout_contract": guard_daily_readout_contract(daily_corpus),
    }

    findings: list[Finding] = []
    passed: list[str] = []
    failed: list[str] = []
    for name, results in guard_results.items():
        findings.extend(results)
        if any(f.severity == SEVERITY_BLOCK for f in results):
            failed.append(name)
        else:
            passed.append(name)

    ok = not any(f.severity == SEVERITY_BLOCK for f in findings)
    return AuditReport(
        generated_at=now.isoformat(),
        registry_path=str(reg_path),
        ok=ok,
        passed_guards=passed,
        failed_guards=failed,
        findings=findings,
        daily_corpus_sources=sources,
    )


# --- Writers ----------------------------------------------------------------


def write_report(report: AuditReport, out_dir: Path) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "governance_audit.json"
    json_path.write_text(
        json.dumps(
            {
                "generated_at": report.generated_at,
                "registry_path": report.registry_path,
                "ok": report.ok,
                "passed_guards": report.passed_guards,
                "failed_guards": report.failed_guards,
                "daily_corpus_sources": report.daily_corpus_sources,
                "findings": [asdict(f) for f in report.findings],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    blocks = [f for f in report.findings if f.severity == SEVERITY_BLOCK]
    warns = [f for f in report.findings if f.severity == SEVERITY_WARN]
    lines = [
        f"# Learning Hub Governance Audit — {report.generated_at[:10]}",
        "",
        f"**Result:** {'PASS ✅' if report.ok else 'FAIL ❌'}",
        f"**Passed guards:** {', '.join(report.passed_guards) or '—'}",
        f"**Failed guards:** {', '.join(report.failed_guards) or '—'}",
        f"**Daily surface scanned:** {', '.join(report.daily_corpus_sources) or '—'}",
        "",
    ]
    if blocks:
        lines += ["## Blocked", ""]
        for f in blocks:
            lines.append(f"- **[{f.guard}] {f.entity}** — {f.detail}")
        lines.append("")
    if warns:
        lines += ["## Warnings", ""]
        for f in warns:
            lines.append(f"- [{f.guard}] {f.entity} — {f.detail}")
        lines.append("")
    if not blocks and not warns:
        lines += ["No findings. All governance guards passed.", ""]

    md_path = out_dir / "LEARNING_HUB_DAILY_AUDIT.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}
