from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbench.workspace._paths import DEFORMATION_RUNS, REPORTS_DIR, WORKSPACE_ROOT


C005_TEXT = "The same broad stress benchmark level can hide different structural morphologies."
CLAIM_VERDICTS = {"SUPPORTED", "WEAKENED", "REJECTED", "INSUFFICIENT_DATA"}


@dataclass(frozen=True)
class C005Evidence:
    run_id: str
    benchmark_rows: list[dict[str, str]]
    residual_tests: dict[str, Any]
    rejection_flags: dict[str, Any]
    operator_diagnostics: dict[str, Any]
    blockers: tuple[str, ...]

    @property
    def claim_verdict(self) -> str:
        if self.blockers:
            return "INSUFFICIENT_DATA"
        if any(bool(value) for value in self.rejection_flags.values()):
            return "WEAKENED"
        return "SUPPORTED"

    @property
    def gate_verdict(self) -> str:
        if self.claim_verdict == "INSUFFICIENT_DATA":
            return "BLOCK"
        if self.claim_verdict == "WEAKENED":
            return "DOWNWEIGHT"
        return "PROMOTE"

    @property
    def severity(self) -> str:
        if self.claim_verdict == "INSUFFICIENT_DATA":
            return "HIGH"
        if self.claim_verdict == "WEAKENED":
            return "MEDIUM"
        return "OK"

    @property
    def required_action(self) -> str:
        if self.claim_verdict == "INSUFFICIENT_DATA":
            return "Populate benchmark comparison, residual tests, rejection flags, and operator diagnostics before C005 can carry paper-facing language."
        if self.claim_verdict == "WEAKENED":
            return "Use cautious morphology language and cite active rejection flags before paper-facing use."
        return "Keep C005 language scoped to morphology separation, not global benchmark outperformance."


def load_evidence(run_id: str, run_dir: Path | None = None) -> C005Evidence:
    run_dir = run_dir or DEFORMATION_RUNS / run_id
    blockers: list[str] = []
    if not run_dir.exists():
        return C005Evidence(run_id, [], {}, {}, {}, (f"run dir missing: {run_dir}",))

    benchmark_rows = _read_benchmark_rows(run_dir / "tables" / "benchmark_comparison.csv", blockers)
    residual_tests = _read_required_json(run_dir / "diagnostics" / "residual_tests.json", "residual_tests", blockers)
    rejection_flags = _read_required_json(run_dir / "diagnostics" / "rejection_flags.json", "rejection_flags", blockers)
    operator_diagnostics = _read_required_json(
        run_dir / "diagnostics" / "operator_diagnostics.json",
        "operator_diagnostics",
        blockers,
    )
    _require_residual_keys(residual_tests, blockers)
    return C005Evidence(
        run_id=run_id,
        benchmark_rows=benchmark_rows,
        residual_tests=residual_tests,
        rejection_flags=rejection_flags,
        operator_diagnostics=operator_diagnostics,
        blockers=tuple(blockers),
    )


def write_report(evidence: C005Evidence, output_dir: Path | None = None) -> Path:
    output_dir = output_dir or REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"c005_morphology_report_{evidence.run_id}.md"
    path.write_text(render_report(evidence), encoding="utf-8")
    json_path = output_dir / f"c005_morphology_report_{evidence.run_id}.json"
    json_path.write_text(json.dumps(evidence_payload(evidence), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def evidence_payload(evidence: C005Evidence) -> dict[str, Any]:
    return {
        "schema_version": "claim_evidence.c005_morphology.v1",
        "claim_id": "C005",
        "claim": C005_TEXT,
        "run_id": evidence.run_id,
        "claim_verdict": evidence.claim_verdict,
        "actionable_verdict": evidence.gate_verdict,
        "severity": evidence.severity,
        "owner": "structural-validation",
        "required_action": evidence.required_action,
        "claim_carrying_allowed": evidence.claim_verdict in {"SUPPORTED", "WEAKENED"},
        "blockers": list(evidence.blockers),
        "benchmark_rows": evidence.benchmark_rows,
        "residual_tests": evidence.residual_tests,
        "rejection_flags": evidence.rejection_flags,
        "operator_diagnostics": evidence.operator_diagnostics,
        "forbidden_claims": [
            "Sigma_t outperforms NFCI globally",
            "global benchmark dominance",
        ],
    }


def render_report(evidence: C005Evidence) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    benchmark_lines = [
        f"- {row.get('name', 'unknown')}: benchmark={_fmt(row.get('benchmark_value'))}, residual={_fmt(row.get('residual_value'))}"
        for row in evidence.benchmark_rows[:12]
    ] or ["- no benchmark rows available"]
    blocker_lines = [f"- {item}" for item in evidence.blockers] or ["- none"]
    residual_keys = sorted(evidence.residual_tests)
    flag_lines = [f"- {key}: {value}" for key, value in sorted(evidence.rejection_flags.items())] or ["- none"]
    operator_summary = _operator_summary(evidence.operator_diagnostics)
    return "\n".join(
        [
            f"# C005 Morphology Benchmark Report - {evidence.run_id}",
            "",
            f"Generated: {generated_at}",
            "",
            "## Actionable Verdict",
            f"- Verdict: {evidence.gate_verdict}",
            f"- Severity: {evidence.severity}",
            "- Owner: structural-validation",
            f"- Required Action: {evidence.required_action}",
            "",
            "## Claim",
            f"- ID: C005",
            f"- Statement: {C005_TEXT}",
            f"- Claim Verdict: {evidence.claim_verdict}",
            "",
            "## Evidence Completeness",
            *blocker_lines,
            "",
            "## Benchmark Comparison",
            *benchmark_lines,
            "",
            "## Residual Tests",
            *(f"- {key}" for key in residual_keys),
            "",
            "## Rejection Flags",
            *flag_lines,
            "",
            "## Operator Diagnostics",
            *operator_summary,
            "",
            "## Claim Boundary",
            "- This report can support morphology-separation language only when Claim Verdict is SUPPORTED or WEAKENED.",
            "- It does not support C003-style global benchmark outperformance language.",
            "",
        ]
    )


def _read_required_json(path: Path, label: str, blockers: list[str]) -> dict[str, Any]:
    if not path.exists():
        blockers.append(f"{label} missing at {_rel(path)}")
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        blockers.append(f"{label} unparseable at {_rel(path)}: {exc}")
        return {}
    if not isinstance(payload, dict) or not payload:
        blockers.append(f"{label} is empty at {_rel(path)}")
        return {}
    return payload


def _read_benchmark_rows(path: Path, blockers: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        blockers.append(f"benchmark_comparison missing at {_rel(path)}")
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    if not rows:
        blockers.append(f"benchmark_comparison has no rows at {_rel(path)}")
        return []
    if any((row.get("name") or "").strip() == "not_available" for row in rows):
        blockers.append("benchmark_comparison contains not_available")
    return rows


def _require_residual_keys(residual_tests: dict[str, Any], blockers: list[str]) -> None:
    expected = {
        "Sigma_resid_vs_aggregate_stress",
        "M_resid_vs_NFCI",
        "D_resid_vs_NFCI",
        "K_resid_vs_vol_jump_tail",
        "X_resid_vs_leverage",
    }
    missing = sorted(key for key in expected if key not in residual_tests)
    if missing:
        blockers.append(f"residual_tests missing required C005 keys: {', '.join(missing)}")


def _operator_summary(payload: dict[str, Any]) -> list[str]:
    if not payload:
        return ["- operator diagnostics unavailable"]
    keys = [
        "operator_count",
        "compression_ratio",
        "non_commutativity_score",
        "irreversible_count",
        "curvature_amplification",
        "mismatch_amplification",
        "shadow_transfer",
    ]
    lines = [f"- {key}: {payload[key]}" for key in keys if key in payload]
    return lines or [f"- populated keys: {', '.join(sorted(payload)[:12])}"]


def _fmt(value: Any) -> str:
    if value in {None, ""}:
        return "missing"
    return str(value)


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="run_id under Output/deformation_runs/")
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args(argv)
    evidence = load_evidence(args.run)
    path = write_report(evidence, Path(args.output_dir) if args.output_dir else None)
    print(f"Wrote {_rel(path)}")
    print(f"C005 Claim Verdict: {evidence.claim_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
