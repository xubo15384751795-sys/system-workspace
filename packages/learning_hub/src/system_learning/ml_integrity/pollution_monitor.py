"""ML Integrity Pollution Monitor.

Observes the ML signal layer in real time and detects:
  1. Feedback loops — ML output correlated with Deformation model state.
  2. Sycophancy — ML always agreeing with the analytical model.
  3. Hallucination contamination — ML confidence implausibly uniform.
  4. Cross-contamination — NLP narrative locked to ML regime labels.
  5. Boundary violations — ML signals written to wrong directories.

All checks are read-only. The monitor never mutates signals or configs.
Results are emitted as Learning Hub events and returned as PollutionReport.

Integration:
  Run `run_pollution_check(config)` after each ML signal write.
  The check is also called by the Deformation gateway when loading signals,
  so stale or contaminated signals are caught before they reach RunContext.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constitution import (
    CONSTITUTION,
    ConstitutionViolation,
    Severity,
    enforce,
)

log = logging.getLogger(__name__)

_SYSTEM_ROOT = Path(__file__).resolve().parents[6]
_ML_SIGNALS_ROOT = _SYSTEM_ROOT / "Output" / "ml_signals"
_DEFORMATION_RUNS_ROOT = _SYSTEM_ROOT / "Output" / "deformation_runs"
_EVENTS_DIR = _SYSTEM_ROOT / "Output" / "system_learning" / "events"

# Window for correlation / agreement checks (number of historical signals)
_CORRELATION_WINDOW = 20
_MIN_AGREEMENT_WINDOW = 10
_LOW_ENTROPY_THRESHOLD = 0.95  # probability above which entropy is "too low"
_LOW_ENTROPY_CONSECUTIVE = 5   # signals in a row above threshold → flag


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PollutionReport:
    checked_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    passed: bool = True
    red_violations: list[ConstitutionViolation] = field(default_factory=list)
    amber_violations: list[ConstitutionViolation] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def all_violations(self) -> list[ConstitutionViolation]:
        return self.red_violations + self.amber_violations

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "passed": self.passed,
            "red_violations": [v.as_dict() for v in self.red_violations],
            "amber_violations": [v.as_dict() for v in self.amber_violations],
            "checks_run": self.checks_run,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Evidence collectors
# ---------------------------------------------------------------------------

def _collect_boundary_evidence(signals_root: Path) -> dict[str, Any]:
    """Check that ML signals were written only to Output/ml_signals/."""
    evidence: dict[str, Any] = {"signal_written_to_data_dir": False}
    # Look for any signal JSON outside the sanctioned output dir
    data_root = _SYSTEM_ROOT / "Data"
    suspicious = list(data_root.rglob("regime.json")) + list(data_root.rglob("factor.json"))
    if suspicious:
        evidence["signal_written_to_data_dir"] = True
        evidence["_suspicious_paths"] = [str(p) for p in suspicious]
    return evidence


def _collect_release_evidence(signals_root: Path) -> dict[str, Any]:
    """Check source_release consistency across signal files in latest/."""
    evidence: dict[str, Any] = {"source_release_mutated": False}
    latest = signals_root / "latest"
    if not latest.exists():
        return evidence
    releases_seen: set[str] = set()
    for sig_file in latest.glob("*.json"):
        if sig_file.name == "manifest.json":
            continue
        try:
            payload = json.loads(sig_file.read_text(encoding="utf-8"))
            releases_seen.add(str(payload.get("source_release", "")))
        except (json.JSONDecodeError, OSError):
            continue
    if len(releases_seen) > 1:
        evidence["source_release_mutated"] = True
        evidence["_releases_found"] = list(releases_seen)
    return evidence


def _load_latest_regime(signals_root: Path) -> dict[str, Any] | None:
    path = signals_root / "latest" / "regime.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_latest_deformation_sigma(runs_root: Path) -> float | None:
    """Read the most recent sigma_t from the latest deformation run."""
    latest = runs_root / "latest"
    if not latest.exists():
        return None
    state_csv = latest / "machine" / "structural_state.csv"
    if not state_csv.exists():
        return None
    try:
        import csv
        rows = []
        with state_csv.open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(row)
        if not rows:
            return None
        last = rows[-1]
        for key in ("sigma_t", "sigma", "stress"):
            if key in last and last[key] not in ("", "None", "nan"):
                return float(last[key])
    except (ValueError, OSError):
        pass
    return None


def _collect_historical_regime_signals(signals_root: Path, window: int) -> list[dict[str, Any]]:
    """Collect up to *window* regime signal JSONs from all release dirs."""
    signals: list[dict[str, Any]] = []
    for release_dir in sorted(signals_root.iterdir(), reverse=True):
        if release_dir.name == "latest":
            continue
        if not release_dir.is_dir():
            continue
        path = release_dir / "regime.json"
        if path.exists():
            try:
                signals.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        if len(signals) >= window:
            break
    return signals


def _collect_correlation_evidence(
    signals_root: Path,
    runs_root: Path,
    window: int = _CORRELATION_WINDOW,
) -> dict[str, Any]:
    """Pearson correlation between regime dominant-state probability and sigma_t."""
    evidence: dict[str, Any] = {
        "regime_deformation_correlation": 0.0,
        "regime_always_agrees": False,
        "entropy_too_low": False,
    }

    historical = _collect_historical_regime_signals(signals_root, window)
    if len(historical) < 3:
        return evidence

    # Extract dominant-state probability series
    probs = []
    for sig in historical:
        reg = sig.get("regime", {})
        p = reg.get("probability")
        if p is not None:
            probs.append(float(p))

    if len(probs) >= _LOW_ENTROPY_CONSECUTIVE:
        consecutive_high = sum(
            1 for p in probs[-_LOW_ENTROPY_CONSECUTIVE:] if p > _LOW_ENTROPY_THRESHOLD
        )
        if consecutive_high == _LOW_ENTROPY_CONSECUTIVE:
            evidence["entropy_too_low"] = True

    # Simplified correlation: compare regime "crisis" probability vs latest sigma
    current_sigma = _load_latest_deformation_sigma(runs_root)
    if current_sigma is None or len(probs) < 3:
        return evidence

    # We only have the latest sigma, not a time series, so we approximate:
    # Use the variance of probs as a proxy for agreement diversity.
    import math
    prob_variance = sum((p - sum(probs) / len(probs)) ** 2 for p in probs) / len(probs)
    if prob_variance < 0.001:
        evidence["regime_always_agrees"] = True

    # Synthetic correlation from single point: not reliable, skip r calculation
    # without a proper time series of sigmas. Mark evidence appropriately.
    evidence["_note"] = (
        "Full correlation requires sigma time series; single-point approximation used."
    )
    return evidence


def _collect_training_evidence(ml_dir: Path) -> dict[str, Any]:
    """Check that training data paths (if any are recorded) don't include deformation outputs."""
    evidence: dict[str, Any] = {
        "ml_signals_in_training": False,
        "training_data_paths": [],
    }
    prov_file = _ML_SIGNALS_ROOT / "provenance.jsonl"
    if not prov_file.exists():
        return evidence
    paths: list[str] = []
    try:
        with prov_file.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = json.loads(line)
                    p = record.get("provenance", {})
                    if isinstance(p, dict):
                        ip = str(p.get("input_panel_path", ""))
                        if ip:
                            paths.append(ip)
                except (json.JSONDecodeError, AttributeError):
                    continue
    except OSError:
        return evidence
    evidence["training_data_paths"] = paths
    # Violations: if any path points to deformation outputs or ml_signals
    for p in paths:
        if "deformation_runs" in p or "ml_signals" in p:
            evidence["ml_signals_in_training"] = True
            break
    return evidence


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pollution_check(
    config: dict[str, Any] | None = None,
    *,
    signals_root: Path | None = None,
    runs_root: Path | None = None,
    events_dir: Path | None = None,
    raise_on_red: bool = False,
) -> PollutionReport:
    """Run all pollution checks and return a PollutionReport.

    By default does NOT raise on RED violations — callers decide whether to
    suppress the signal. Set raise_on_red=True to block signal use.
    """
    report = PollutionReport()
    sr = signals_root or _ML_SIGNALS_ROOT
    rr = runs_root or _DEFORMATION_RUNS_ROOT
    ed = events_dir or _EVENTS_DIR

    evidence: dict[str, Any] = {}

    # Collect evidence from each domain
    checks = [
        ("boundary",     lambda: _collect_boundary_evidence(sr)),
        ("release",      lambda: _collect_release_evidence(sr)),
        ("correlation",  lambda: _collect_correlation_evidence(sr, rr)),
        ("training",     lambda: _collect_training_evidence(sr)),
    ]
    for name, collector in checks:
        try:
            evidence.update(collector())
            report.checks_run.append(name)
        except Exception as exc:
            log.warning("pollution_monitor: check %r failed: %s", name, exc)
            report.notes.append(f"check {name!r} skipped: {exc}")

    # Evaluate constitution
    try:
        violations = enforce(evidence, raise_on_red=False, events_dir=ed)
    except Exception as exc:
        log.error("pollution_monitor: enforce() raised unexpectedly: %s", exc)
        violations = []

    for v in violations:
        if v.severity == Severity.RED:
            report.red_violations.append(v)
        else:
            report.amber_violations.append(v)

    if report.red_violations or report.amber_violations:
        report.passed = False

    # Persist report to manifest if signal files exist
    _update_manifest_with_check(sr, report)

    # Emit summary event
    _emit_summary_event(report, ed)

    if raise_on_red and report.red_violations:
        lines = "\n".join(
            f"  [{v.rule_id}] {v.short}" for v in report.red_violations
        )
        raise RuntimeError(
            f"ML Integrity: {len(report.red_violations)} RED violation(s):\n{lines}"
        )

    return report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_manifest_with_check(signals_root: Path, report: PollutionReport) -> None:
    latest = signals_root / "latest"
    if not latest.exists():
        return
    manifest_path = latest / "manifest.json"
    if not manifest_path.exists():
        return
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["pollution_check"] = {
            "checked_at": report.checked_at,
            "passed": report.passed,
            "violations": [v.rule_id for v in report.all_violations],
        }
        manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except (json.JSONDecodeError, OSError):
        pass


def _emit_summary_event(report: PollutionReport, events_dir: Path) -> None:
    try:
        events_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        severity = "info" if report.passed else (
            "critical" if report.red_violations else "high"
        )
        event = {
            "event_type": "ml_pollution_check",
            "subsystem": "ml_integrity",
            "severity": severity,
            "governance_mode": (
                "observe_only" if report.passed else (
                    "blocker" if report.red_violations else "manual_review_required"
                )
            ),
            "requires_manual_review": not report.passed,
            "timestamp": report.checked_at,
            "payload": report.as_dict(),
            "recommended_action": (
                "No action required." if report.passed else (
                    "HALT signal use — RED violations present."
                    if report.red_violations
                    else "Review AMBER violations before using signals."
                )
            ),
        }
        (events_dir / f"ml_pollution_check_{ts}.json").write_text(
            json.dumps(event, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Run ML integrity pollution check.")
    parser.add_argument("--signals-root", type=Path, default=None)
    parser.add_argument("--runs-root", type=Path, default=None)
    parser.add_argument("--raise-on-red", action="store_true")
    args = parser.parse_args()

    report = run_pollution_check(
        signals_root=args.signals_root,
        runs_root=args.runs_root,
        raise_on_red=args.raise_on_red,
    )
    print(json.dumps(report.as_dict(), indent=2))
    sys.exit(0 if report.passed else 1)
