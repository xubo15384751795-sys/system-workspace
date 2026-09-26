"""ML Integrity Constitution.

Defines absolute red lines that no ML, DL, or NLP signal in this system
may cross — ever. These rules are immutable: they cannot be relaxed by
config, by ML model confidence, by observed correlations, or by any
automated decision process. Changes require explicit human governance
action logged to the Learning Hub violation ledger.

Design principle: the analytical framework's preferences (thresholds,
weights, mechanisms, proxy definitions) must be derived from economic
theory and empirical evidence — not inferred from ML output agreement.
Any tendency of an ML model to "learn to please" the existing model is
treated as contamination, not as validation.

Rules are grouped:
  RED     — blocker; must halt signal promotion.
  AMBER   — high severity; requires manual review before use.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from system_runtime.context import RuntimeContext

logger = logging.getLogger(__name__)


class Severity(str, Enum):
    RED = "RED"      # absolute blocker — signal must not be used
    AMBER = "AMBER"  # requires manual review before use


class ConstitutionEvaluationError(RuntimeError):
    """Raised when a constitution rule cannot be evaluated safely."""


@dataclass(frozen=True)
class Rule:
    id: str
    severity: Severity
    short: str
    description: str
    check: Callable[[dict[str, Any]], bool]  # returns True when VIOLATED

    def evaluate(self, evidence: dict[str, Any]) -> bool:
        try:
            return self.check(evidence)
        except Exception as exc:
            # An unknown rule result is not evidence of compliance. Keep the
            # diagnostic bounded to the exception type and rule id so a bad
            # check cannot leak evidence payloads into logs or the raised
            # governance error.
            logger.error(
                "ML integrity rule evaluation failed: rule_id=%s error_type=%s",
                self.id,
                type(exc).__name__,
            )
            raise ConstitutionEvaluationError(
                f"ML integrity rule {self.id} could not be evaluated "
                f"({type(exc).__name__}); signal use is blocked."
            ) from None


@dataclass
class ConstitutionViolation:
    rule_id: str
    severity: Severity
    short: str
    evidence_summary: str
    detected_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "short": self.short,
            "evidence_summary": self.evidence_summary,
            "detected_at": self.detected_at,
        }


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------
# Evidence dict keys used by rules:
#   signal_output_paths   list[str]  — paths the ML layer wrote to
#   config_mutations      list[str]  — config keys ML layer attempted to change
#   proxy_definitions     dict       — current proxy definitions
#   ml_influenced_proxies list[str]  — proxies whose definitions reference ML output
#   regime_to_weight_map  dict       — any mapping from regime label to M/D/K/X weight
#   training_data_paths   list[str]  — paths used for training data
#   ml_signals_in_training bool      — whether ML signal files were in training input
#   nlp_label_source      str        — source of NLP training labels
#   narrative_from_regime bool       — whether NLP narrative was derived from ML regime
#   regime_deformation_correlation float  — Pearson r between regime probs and deformation sigma
#   regime_always_agrees  bool       — ML regime never contradicted deformation state
#   entropy_too_low       bool       — signal confidence implausibly uniform over window
#   source_release_mutated bool      — source_release field changed after initial write
#   signal_written_to_data_dir bool  — signal file written under Data/
# ---------------------------------------------------------------------------

_RULES: list[Rule] = [

    # --- RED LINES ---

    Rule(
        id="CONST-01",
        severity=Severity.RED,
        short="ML output written to Data/ directory",
        description=(
            "ML signal files must only be written to Output/state/ml_signals/. "
            "Any write to Data/, Harvester exports, or raw directories is an "
            "absolute violation that could corrupt the evidence base."
        ),
        check=lambda e: bool(e.get("signal_written_to_data_dir", False)),
    ),

    Rule(
        id="CONST-02",
        severity=Severity.RED,
        short="source_release mutated after initial write",
        description=(
            "A signal's source_release field is a contract with the consumer: "
            "it must be set at write time and never modified. Mutation breaks "
            "the freshness gate and allows stale signals to appear valid."
        ),
        check=lambda e: bool(e.get("source_release_mutated", False)),
    ),

    Rule(
        id="CONST-03",
        severity=Severity.RED,
        short="ML output fed back into Harvester release pipeline",
        description=(
            "Harvester releases must be built from raw source data only. "
            "If any ML signal file appears in the training inputs or evidence "
            "panel of a Harvester release, the feedback loop is closed and "
            "the entire evidence base is contaminated."
        ),
        check=lambda e: bool(e.get("ml_signals_in_training", False)),
    ),

    Rule(
        id="CONST-04",
        severity=Severity.RED,
        short="ML regime labels used as proxy definitions (M/D/K/X)",
        description=(
            "Proxy definitions (M=mismatch, D=DoF, K=curvature, X=shadow) "
            "must be derived from economic theory and structural mechanics. "
            "Regime labels from an HMM are probabilistic summaries of patterns "
            "already latent in the data — using them as proxy definitions "
            "introduces circular reasoning."
        ),
        check=lambda e: bool(e.get("ml_influenced_proxies")),
    ),

    Rule(
        id="CONST-05",
        severity=Severity.RED,
        short="ML confidence scores used as M/D/K/X weights in ODE/mechanism",
        description=(
            "The regime probability or factor loadings from the ML layer must "
            "not be used to scale, gate, or shift mechanism weights in the "
            "Deformation ODE. This includes soft gating, multiplicative "
            "scaling, or threshold modification."
        ),
        check=lambda e: bool((e.get("regime_to_weight_map") or {})),
    ),

    Rule(
        id="CONST-06",
        severity=Severity.RED,
        short="NLP pipeline trained on ML signal labels",
        description=(
            "NLP training labels must come from human-annotated ground truth "
            "or from the empirical event log — not from ML regime/factor outputs. "
            "Using ML outputs as NLP labels creates a hidden feedback loop where "
            "NLP 'confirms' ML which confirms deformation state."
        ),
        check=lambda e: bool(e.get("nlp_label_source") == "ml_signal"),
    ),

    Rule(
        id="CONST-07",
        severity=Severity.RED,
        short="NLP narrative derived from ML regime output",
        description=(
            "Narrative generation must use empirical event data and structured "
            "text sources. If narrative.regime_source == 'ml_signal', the NLP "
            "pipeline is anchored to ML outputs rather than observed evidence."
        ),
        check=lambda e: bool(e.get("narrative_from_regime", False)),
    ),

    Rule(
        id="CONST-08",
        severity=Severity.RED,
        short="ML model retrained on Deformation output",
        description=(
            "ML model training data must consist solely of frozen Harvester "
            "export panels. If any Deformation run output (snapshots, sigma "
            "timelines, structural state CSVs) appears in training paths, "
            "the ML model is fitting to the framework's own conclusions."
        ),
        check=lambda e: any(
            "deformation_runs" in str(p) or "snapshot" in str(p).lower()
            for p in (e.get("training_data_paths") or [])
        ),
    ),

    # --- AMBER LINES (high severity, requires manual review) ---

    Rule(
        id="CONT-01",
        severity=Severity.AMBER,
        short="Suspicious ML-deformation alignment (correlation > 0.9)",
        description=(
            "When ML regime probability and the deformation sigma are correlated "
            "above 0.9 over a rolling window, the ML model may have learned to "
            "shadow the analytical model rather than independently characterising "
            "the data. This is the canonical sycophancy pattern."
        ),
        check=lambda e: float(e.get("regime_deformation_correlation", 0.0)) > 0.9,
    ),

    Rule(
        id="CONT-02",
        severity=Severity.AMBER,
        short="ML regime never contradicts deformation state",
        description=(
            "Over a long window, if the ML regime label always agrees with the "
            "deformation state label, the model is a mirror, not a signal. "
            "A genuinely independent ML signal should show occasional disagreement."
        ),
        check=lambda e: bool(e.get("regime_always_agrees", False)),
    ),

    Rule(
        id="CONT-03",
        severity=Severity.AMBER,
        short="Signal confidence implausibly uniform (entropy too low)",
        description=(
            "If a regime signal consistently assigns probability > 0.95 to one "
            "state across many successive signals, the HMM has collapsed to a "
            "near-deterministic predictor. This suggests overfitting or that the "
            "model has learned to mimic a fixed label rather than the data."
        ),
        check=lambda e: bool(e.get("entropy_too_low", False)),
    ),

    Rule(
        id="CONT-04",
        severity=Severity.AMBER,
        short="ML config mutations attempted",
        description=(
            "Any attempt by the ML layer to modify system configuration keys — "
            "thresholds, proxy weights, mechanism enables — is a boundary "
            "violation. ML context is read-only supplementary information."
        ),
        check=lambda e: bool(e.get("config_mutations")),
    ),
]

CONSTITUTION: list[Rule] = _RULES


# ---------------------------------------------------------------------------
# Enforcement
# ---------------------------------------------------------------------------

def enforce(
    evidence: dict[str, Any],
    *,
    raise_on_red: bool = True,
    events_dir: Path | None = None,
) -> list[ConstitutionViolation]:
    """Evaluate all rules against *evidence*.

    Returns list of violations. Emits Learning Hub events for each.
    Raises ConstitutionError (subclass of RuntimeError) on first RED
    violation when raise_on_red=True.
    """
    violations: list[ConstitutionViolation] = []
    for rule in CONSTITUTION:
        if rule.evaluate(evidence):
            summary = _build_summary(rule, evidence)
            v = ConstitutionViolation(
                rule_id=rule.id,
                severity=rule.severity,
                short=rule.short,
                evidence_summary=summary,
            )
            violations.append(v)
            _emit_event(v, events_dir)

    if raise_on_red:
        reds = [v for v in violations if v.severity == Severity.RED]
        if reds:
            lines = "\n".join(f"  [{v.rule_id}] {v.short}" for v in reds)
            raise ConstitutionError(
                f"ML Integrity: {len(reds)} RED violation(s) — signal must be suppressed:\n{lines}"
            )

    return violations


class ConstitutionError(RuntimeError):
    """Raised when a RED rule is violated and raise_on_red=True."""


def _build_summary(rule: Rule, evidence: dict[str, Any]) -> str:
    key_fields = {
        "CONST-01": "signal_written_to_data_dir",
        "CONST-02": "source_release_mutated",
        "CONST-03": "ml_signals_in_training",
        "CONST-04": "ml_influenced_proxies",
        "CONST-05": "regime_to_weight_map",
        "CONST-06": "nlp_label_source",
        "CONST-07": "narrative_from_regime",
        "CONST-08": "training_data_paths",
        "CONT-01": "regime_deformation_correlation",
        "CONT-02": "regime_always_agrees",
        "CONT-03": "entropy_too_low",
        "CONT-04": "config_mutations",
    }
    key = key_fields.get(rule.id, "")
    val = evidence.get(key, "<not provided>")
    return f"{key}={json.dumps(val, default=str)}"


def _emit_event(violation: ConstitutionViolation, events_dir: Path | None) -> None:
    root = events_dir or (
        RuntimeContext.current_context().output_root / "system_learning" / "events"
    )
    try:
        root.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        event_file = root / f"ml_constitution_{violation.rule_id}_{ts}.json"
        event = {
            "event_type": "ml_constitution_violation",
            "subsystem": "ml_integrity",
            "severity": violation.severity.value.lower(),
            "governance_mode": "blocker" if violation.severity == Severity.RED else "manual_review_required",
            "requires_manual_review": True,
            "timestamp": violation.detected_at,
            "payload": violation.as_dict(),
            "recommended_action": (
                "HALT signal promotion and investigate."
                if violation.severity == Severity.RED
                else "Flag for human review before using this signal."
            ),
        }
        event_file.write_text(json.dumps(event, indent=2) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("Unable to write ML integrity constitution event: %s", event_file, exc_info=True)
