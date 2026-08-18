"""verify_only — implementer/verifier separation workflow.

Enforces that verification is performed by a separate agent than the
implementer.  Must run actual commands (not just assert).  Cannot PASS
without executed command evidence.  PARTIAL verdicts must list residual risks.

Auto-selects checks based on artifact type:
  - docs-only:        link/audit/yaml parse checks
  - Python:           unit tests / import checks
  - Harvester release: schema / hash / catalog verification
  - Deformation snapshot: snapshot validation / proxy audit
  - Benchmark:        no-lookahead / baseline rank / ablation

Usage:
  from workflows.verify_only import VerificationRunner, CheckSelector

  selector = CheckSelector()
  checks = selector.select(target_artifact, changed_files, claimed_outcome)
  runner = VerificationRunner()
  result = runner.run(checks, mode="verify")
  print(result.verdict)  # PASS | FAIL | PARTIAL
"""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
logger = logging.getLogger(__name__)


# ── data structures ─────────────────────────────────────────────────────

@dataclass
class CheckSpec:
    """Specification for a single verification check."""
    check_id: str
    check_type: str          # command, link_check, manual_required, tool_run
    command: str = ""        # shell command, path, or tool invocation
    expected_exit_code: int = 0
    description: str = ""


@dataclass
class CheckResult:
    """Result of executing a single verification check."""
    check_id: str
    command: str
    exit_code: int
    observed: str            # stdout/stderr or tool result summary
    passed: bool
    detail: str = ""


@dataclass
class VerificationVerdict:
    """Final verification verdict with evidence."""
    verdict: str             # PASS | FAIL | PARTIAL
    target: str              # artifact or release/snapshot identifier
    checks: list[CheckResult] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    residual_risks: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    commands_executed: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "target": self.target,
            "checks": [
                {
                    "check_id": c.check_id,
                    "command": c.command,
                    "exit_code": c.exit_code,
                    "observed": c.observed[:500],
                    "passed": c.passed,
                }
                for c in self.checks
            ],
            "blockers": self.blockers,
            "residual_risks": self.residual_risks,
            "evidence": self.evidence,
            "commands_executed": self.commands_executed,
            "timestamp": self.timestamp,
        }


# ── check selector ──────────────────────────────────────────────────────

class CheckSelector:
    """Auto-select verification checks based on artifact type."""

    def select(
        self,
        target_artifact: str,
        changed_files: list[str],
        claimed_outcome: str,
    ) -> list[CheckSpec]:
        """Select appropriate checks for the given target.

        Args:
            target_artifact: e.g. "harvester_release", "deformation_snapshot",
                             "benchmark_report", "source_code", "docs"
            changed_files:   list of file paths that changed
            claimed_outcome: what the implementer claims was achieved
        """
        checks: list[CheckSpec] = []

        if target_artifact in ("harvester_release", "harvester"):
            checks.extend(self._harvester_release_checks(changed_files))
        elif target_artifact in ("deformation_snapshot", "deformation"):
            checks.extend(self._deformation_snapshot_checks(changed_files))
        elif target_artifact in ("benchmark", "benchmark_report"):
            checks.extend(self._benchmark_checks(changed_files))
        elif target_artifact in ("source_code", "python"):
            checks.extend(self._python_checks(changed_files))
        elif target_artifact == "docs":
            checks.extend(self._docs_checks(changed_files))

        # Always add artifact type-specific tool checks
        checks.extend(self._common_checks(changed_files, target_artifact))

        return checks

    def _harvester_release_checks(self, files: list[str]) -> list[CheckSpec]:
        cat_path = WORKBENCH_ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
        cmd = "python3 -c \"import json; json.load(open('" + str(cat_path) + "'))\""
        return [
            CheckSpec("harvester_verify_release", "tool_run",
                      command="harvester.verify_release", description="Release integrity verification"),
            CheckSpec("catalog_schema", "tool_run",
                      command="harvester.inspect_release", description="Catalog schema inspection"),
            CheckSpec("release_hash", "command",
                      command=cmd, description="Catalog JSON parseable"),
        ]

    def _deformation_snapshot_checks(self, files: list[str]) -> list[CheckSpec]:
        return [
            CheckSpec("snapshot_validate", "tool_run",
                      command="deformation.validate_snapshot", description="Snapshot schema validation"),
            CheckSpec("snapshot_inspect", "tool_run",
                      command="deformation.inspect_snapshot", description="Snapshot proxy/state inspection"),
            CheckSpec("operator_trace", "tool_run",
                      command="deformation.inspect_operator_trace", description="Operator trace inspection"),
        ]

    def _benchmark_checks(self, files: list[str]) -> list[CheckSpec]:
        return [
            CheckSpec("no_lookahead", "tool_run",
                      command="deformation.validate_snapshot", description="No-lookahead validation"),
            CheckSpec("proxy_boundary", "tool_run",
                      command="deformation.inspect_operator_trace", description="Benchmark leakage check"),
            CheckSpec(
                "baseline_rank",
                "manual_required",
                command="baseline_rank_evidence",
                description="Baseline rank comparison requires a real evidence artifact",
            ),
        ]

    def _python_checks(self, files: list[str]) -> list[CheckSpec]:
        checks = []
        for f in files:
            if f.endswith(".py"):
                mod_path = Path(f).with_suffix("").as_posix().replace("/", ".")
                mod_path = mod_path.replace("Structural Research Harness.", "")
                cmd = "python3 -c \"import " + mod_path + "\""
                checks.append(CheckSpec(f"import_{Path(f).stem}", "command",
                    command=cmd, expected_exit_code=0,
                    description=f"Import check: {f}",
                ))
        # Unit test check for any test files
        test_files = [f for f in files if "test" in Path(f).name.lower() or Path(f).match("*_test.py")]
        if test_files:
            for tf in test_files:
                checks.append(CheckSpec(
                    f"test_{Path(tf).stem}", "command",
                    command=f"python3 {tf}",
                    description=f"Run tests: {tf}",
                ))
        return checks

    def _docs_checks(self, files: list[str]) -> list[CheckSpec]:
        checks = []
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in (".yaml", ".yml"):
                cmd = "python3 -c \"import yaml; yaml.safe_load(open('" + f + "'))\""
                checks.append(CheckSpec(f"yaml_parse_{Path(f).stem}", "command", command=cmd, description=f"YAML parse: {f}"))
            elif ext in (".json",):
                cmd = "python3 -c \"import json; json.load(open('" + f + "'))\""
                checks.append(CheckSpec(f"json_parse_{Path(f).stem}", "command", command=cmd, description=f"JSON parse: {f}"))
            elif ext in (".md",):
                checks.append(CheckSpec(
                    f"link_check_{Path(f).stem}",
                    "link_check",
                    command=f,
                    description=f"Link check: {f}",
                ))
        return checks

    def _common_checks(self, files: list[str], target: str) -> list[CheckSpec]:
        boundary_path = HARNESS_ROOT / "policies" / "boundary_rules.yaml"
        flags_path = HARNESS_ROOT / "policies" / "feature_flags.yaml"
        return [
            CheckSpec("boundary_rules_load", "command",
                      command="python3 -c \"import yaml; yaml.safe_load(open('" + str(boundary_path) + "'))\"",
                      description="Boundary rules YAML parseable"),
            CheckSpec("feature_flags_load", "command",
                      command="python3 -c \"import yaml; yaml.safe_load(open('" + str(flags_path) + "'))\"",
                      description="Feature flags YAML parseable"),
        ]


# ── verification runner ─────────────────────────────────────────────────

class VerificationRunner:
    """Execute verification checks and produce a verdict.

    Enforces:
      - No PASS without executed commands
      - No PASS when any command failed
      - PARTIAL must list residual risks
      - Verification event written to Learning Hub
    """

    def run(
        self,
        checks: list[CheckSpec],
        target: str = "",
        mode: str = "verify",
        implementer_agent: str = "",
    ) -> VerificationVerdict:
        """Run all checks and produce a verdict.

        Args:
            checks:            List of CheckSpec to execute
            target:            What is being verified (release_id, run_id, etc.)
            mode:              Agent mode for tool runs ("verify")
            implementer_agent: Agent ID of the implementer (must differ from "verify")
        """
        results: list[CheckResult] = []
        blockers: list[str] = []

        for check in checks:
            result = self._execute(check, mode)
            results.append(result)
            if not result.passed:
                blockers.append(f"{check.check_id}: {result.observed[:200]}")

        # Determine verdict
        verdict = self._determine_verdict(results, blockers)

        # Build evidence
        evidence = {
            "checks": [
                {
                    "check_id": r.check_id,
                    "command": r.command,
                    "exit_code": r.exit_code,
                    "passed": r.passed,
                    "detail": r.detail,
                }
                for r in results
            ],
            "total_checks": len(results),
            "passed_checks": sum(1 for r in results if r.passed),
            "failed_checks": sum(1 for r in results if not r.passed),
        }

        verdict_obj = VerificationVerdict(
            verdict=verdict,
            target=target,
            checks=results,
            blockers=blockers,
            residual_risks=[] if verdict != "PARTIAL" else [
                f"Partial check: {r.check_id}" for r in results if not r.passed
            ],
            evidence=evidence,
            commands_executed=len(results),
        )

        # A verification PASS is not durable unless its evidence event was
        # accepted by the Learning Hub writer. Keep the local verdict
        # fail-closed when the mandatory audit sink is missing or fails.
        event_written = self._write_verification_event(verdict_obj)
        verdict_obj.evidence["verification_event_written"] = event_written
        if not event_written:
            verdict_obj.verdict = "FAIL"
            verdict_obj.blockers.append("verification_event_write_failed")
            verdict_obj.residual_risks.append("verification evidence is not durable")

        return verdict_obj

    def _execute(self, check: CheckSpec, mode: str) -> CheckResult:
        """Execute a single check.  Tool runs go through the registry."""
        if check.check_type == "tool_run":
            return self._execute_tool(check, mode)
        if check.check_type == "link_check":
            return self._execute_link_check(check)
        if check.check_type == "manual_required":
            return self._execute_manual_required(check)
        return self._execute_command(check)

    def _execute_manual_required(self, check: CheckSpec) -> CheckResult:
        """Fail explicitly when a required evidence-producing check is absent."""
        observed = f"NOT_IMPLEMENTED: {check.description}"
        return CheckResult(
            check_id=check.check_id,
            command=check.command,
            exit_code=2,
            observed=observed,
            passed=False,
            detail=observed,
        )

    def _execute_link_check(self, check: CheckSpec) -> CheckResult:
        """Validate local Markdown links without performing network requests."""
        document = Path(check.command)
        if not document.is_absolute():
            document = WORKBENCH_ROOT / document
        if not document.is_file():
            observed = f"Markdown file does not exist: {document}"
            return CheckResult(check.check_id, check.command, 1, observed, False, observed)

        try:
            text = document.read_text(encoding="utf-8")
        except OSError as exc:
            observed = f"Unable to read Markdown file: {type(exc).__name__}"
            return CheckResult(check.check_id, check.command, 1, observed, False, observed)

        missing: list[str] = []
        link_count = 0
        pattern = re.compile(r"(?<!!)\[[^\]]*\]\((<[^>]+>|[^)\s]+)(?:\s+\"[^\"]*\")?\)")
        for match in pattern.finditer(text):
            raw_target = match.group(1)
            target = raw_target[1:-1] if raw_target.startswith("<") else raw_target
            if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            link_count += 1
            target = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not target:
                continue
            linked_path = Path(target)
            if not linked_path.is_absolute():
                linked_path = document.parent / linked_path
            if not linked_path.exists():
                missing.append(target)

        if missing:
            observed = f"missing local links ({len(missing)}): {', '.join(missing[:10])}"
            return CheckResult(check.check_id, check.command, 1, observed, False, observed)

        observed = f"validated {link_count} local Markdown link(s); external links not fetched"
        return CheckResult(check.check_id, check.command, 0, observed, True, observed)

    def _execute_tool(self, check: CheckSpec, mode: str) -> CheckResult:
        """Execute a tool via the system registry."""
        try:
            from tools.registry import run_tool
            tool_id = check.command
            result = run_tool(tool_id, {}, mode=mode)
            ok = result.get("ok", False)
            return CheckResult(
                check_id=check.check_id,
                command=f"system tools run {tool_id} --mode {mode}",
                exit_code=0 if ok else 1,
                observed=result.get("summary", str(result)),
                passed=ok,
                detail=result.get("summary", ""),
            )
        except Exception as e:
            return CheckResult(
                check_id=check.check_id,
                command=check.command,
                exit_code=1,
                observed=str(e),
                passed=False,
                detail=str(e)[:200],
            )

    def _execute_command(self, check: CheckSpec) -> CheckResult:
        """Execute a shell command."""
        try:
            proc = subprocess.run(
                shlex.split(check.command), capture_output=True, text=True,
                timeout=30, cwd=str(WORKBENCH_ROOT),
            )
            passed = proc.returncode == check.expected_exit_code
            observed = proc.stdout.strip() or proc.stderr.strip()
            return CheckResult(
                check_id=check.check_id,
                command=check.command,
                exit_code=proc.returncode,
                observed=observed[:500] if observed else "(no output)",
                passed=passed,
                detail=observed[:200] if observed else "no output",
            )
        except subprocess.TimeoutExpired:
            return CheckResult(
                check_id=check.check_id,
                command=check.command,
                exit_code=1,
                observed="Command timed out (30s)",
                passed=False,
                detail="Command timed out",
            )
        except Exception as e:
            return CheckResult(
                check_id=check.check_id,
                command=check.command,
                exit_code=1,
                observed=str(e),
                passed=False,
                detail=str(e)[:200],
            )

    def _determine_verdict(self, results: list[CheckResult], blockers: list[str]) -> str:
        # Cannot PASS without executing commands
        if not results:
            return "FAIL"

        all_passed = all(r.passed for r in results)

        if all_passed and not blockers:
            return "PASS"

        if blockers:
            # If all failed passes are expected/acceptable, consider PARTIAL
            return "FAIL"

        return "FAIL"  # fallthrough

    def _write_verification_event(self, verdict: VerificationVerdict) -> bool:
        try:
            from events.system_event_writer import write_verification_result
            return bool(write_verification_result(
                tool_id="workflow.verify_only",
                subsystem="harness",
                mode="verify",
                ok=(verdict.verdict == "PASS"),
                verdict=verdict.verdict,
                evidence=verdict.evidence,
                summary=f"Verification {verdict.verdict} for {verdict.target}",
                blockers=verdict.blockers,
                residual_risks=verdict.residual_risks,
            ))
        except Exception:
            logger.warning("Unable to record verification evidence", exc_info=True)
            return False


# ── public API ──────────────────────────────────────────────────────────

def run_verification(
    target_artifact: str,
    changed_files: list[str],
    claimed_outcome: str,
    implementer_agent: str = "",
    mode: str = "verify",
) -> VerificationVerdict:
    """Run a complete verification workflow.

    Args:
        target_artifact: "harvester_release", "deformation_snapshot", "benchmark", "source_code", "docs"
        changed_files:   List of file paths changed by implementer
        claimed_outcome: What the implementer claims
        implementer_agent: Agent ID who did the implementation (must not be "verify")
        mode:            Agent mode (must be "verify")

    Returns:
        VerificationVerdict with PASS/FAIL/PARTIAL

    Raises:
        ValueError: If implementer_agent is "verify" (cannot self-verify)
    """
    if implementer_agent == "verify":
        raise ValueError("Verification agent cannot verify its own work. Implementer and verifier must be separate.")

    if mode != "verify":
        raise ValueError(f"Verification workflow requires mode='verify', got '{mode}'")

    selector = CheckSelector()
    checks = selector.select(target_artifact, changed_files, claimed_outcome)

    runner = VerificationRunner()
    return runner.run(checks, target=target_artifact, mode=mode, implementer_agent=implementer_agent)
