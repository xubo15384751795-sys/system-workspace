"""Event-triggered mechanism evaluator.

READS: mechanism_tiers.yaml (trigger conditions)
       mechanism_features.yaml (mechanism metadata)
WRITES: Output/caselab/event_triggers/ only

Evaluates discrete trigger conditions against a set of observables
to activate Tier 2 (event-triggered) mechanisms that have no
continuous market features.
"""
from __future__ import annotations

import json
import logging
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from system_runtime.paths import WorkspacePaths

logger = logging.getLogger(__name__)

DATA_DIR = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_training"
OUTPUT_DIR = WorkspacePaths.discover().root / "Output" / "caselab" / "event_triggers"

# ── Condition evaluator ─────────────────────────────────────────────────

_OPS = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}

# Tokenize: number, string, operator, AND, OR, parens, variable name
_TOKEN_RE = re.compile(
    r"""
    \s*(
        \( | \)                           # parens
        | >= | <= | == | !=               # multi-char ops
        | [><]                            # single-char ops
        | AND | OR                        # boolean connectives
        | True | False                    # booleans
        | -?\d+(?:\.\d+)?                # numbers
        | [A-Za-z_][A-Za-z0-9_.]*        # identifiers
    )
    """,
    re.VERBOSE,
)


def _tokenize(expr: str) -> list[str]:
    """Tokenize a trigger condition expression."""
    tokens: list[str] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m:
            raise SyntaxError(f"Cannot parse at position {pos}: {expr[pos:pos+20]}")
        tokens.append(m.group(1).strip())
        pos = m.end()
    return tokens


def _parse_value(token: str, observables: dict[str, Any]) -> Any:
    """Resolve a token to a value: number, bool, or observable lookup."""
    if token == "True":
        return True
    if token == "False":
        return False
    try:
        if "." in token:
            return float(token)
        return int(token)
    except ValueError:
        logger.debug("Condition token is not numeric; resolving as observable: %s", token)
    # Look up in observables
    return observables.get(token, 0)


def evaluate_condition(condition: str, observables: dict[str, Any]) -> bool:
    """Evaluate a boolean trigger condition against observables.

    Supports:
        - Comparisons: var > 0.05, flag == True
        - Boolean connectives: AND, OR
        - Parentheses for grouping
        - Numeric literals, bool literals, observable variable names

    Parameters
    ----------
    condition : str
        Boolean expression, e.g. "(dd_vel_SPY_5d > 0.03) AND (rv_SPY_20d > 0.25)"
    observables : dict
        Current observable values keyed by variable name.

    Returns
    -------
    bool
        Whether the condition is satisfied.
    """
    tokens = _tokenize(condition)
    result, _ = _eval_or(tokens, 0, observables)
    return bool(result)


def _eval_or(tokens: list[str], pos: int, obs: dict[str, Any]) -> tuple[bool, int]:
    """Evaluate OR expression."""
    left, pos = _eval_and(tokens, pos, obs)
    while pos < len(tokens) and tokens[pos] == "OR":
        pos += 1  # skip OR
        right, pos = _eval_and(tokens, pos, obs)
        left = left or right
    return left, pos


def _eval_and(tokens: list[str], pos: int, obs: dict[str, Any]) -> tuple[bool, int]:
    """Evaluate AND expression."""
    left, pos = _eval_comparison(tokens, pos, obs)
    while pos < len(tokens) and tokens[pos] == "AND":
        pos += 1  # skip AND
        right, pos = _eval_comparison(tokens, pos, obs)
        left = left and right
    return left, pos


def _eval_comparison(tokens: list[str], pos: int, obs: dict[str, Any]) -> tuple[bool, int]:
    """Evaluate comparison or parenthesized expression."""
    if pos < len(tokens) and tokens[pos] == "(":
        pos += 1  # skip (
        result, pos = _eval_or(tokens, pos, obs)
        if pos < len(tokens) and tokens[pos] == ")":
            pos += 1  # skip )
        return result, pos

    # Parse: value op value
    left_val = _parse_value(tokens[pos], obs)
    pos += 1

    if pos >= len(tokens) or tokens[pos] not in _OPS:
        # Bare value (truthy check)
        return bool(left_val), pos

    op_func = _OPS[tokens[pos]]
    pos += 1

    right_val = _parse_value(tokens[pos], obs)
    pos += 1

    try:
        return op_func(left_val, right_val), pos
    except TypeError:
        return False, pos


# ── Event Trigger Engine ────────────────────────────────────────────────

@dataclass
class TriggeredMechanism:
    """A mechanism activated by an event trigger."""
    name: str
    tier: str
    trigger_condition: str
    event_type: str
    description: str
    related_mechanisms: list[str]
    features: list[str]
    signal: str
    k_state_direction: str
    related_variables: list[str]
    related_entities: list[str]
    related_cases: list[str]
    tags: list[str]


@dataclass
class TriggerResult:
    """Result of evaluating all event triggers against observables."""
    triggered: list[TriggeredMechanism] = field(default_factory=list)
    evaluated: int = 0
    errors: list[str] = field(default_factory=list)
    observables_used: dict[str, Any] = field(default_factory=dict)

    @property
    def activation_count(self) -> int:
        return len(self.triggered)

    def mechanism_names(self) -> list[str]:
        return [m.name for m in self.triggered]

    def related_mechanism_names(self) -> list[str]:
        """All mechanisms related to triggered ones (for cascade)."""
        names: set[str] = set()
        for m in self.triggered:
            names.update(m.related_mechanisms)
        return sorted(names)


class EventTriggerEngine:
    """Evaluate event triggers against observables.

    Usage:
        engine = EventTriggerEngine()
        result = engine.evaluate({
            "dd_vel_SPY_5d": 0.04,
            "rv_SPY_20d": 0.30,
        })
        for m in result.triggered:
            print(f"Activated: {m.name}")
    """

    def __init__(
        self,
        tiers_path: Path | None = None,
        features_path: Path | None = None,
    ):
        self._tiers_path = tiers_path or DATA_DIR / "mechanism_tiers.yaml"
        self._features_path = features_path or DATA_DIR / "mechanism_features.yaml"
        self._tiers: dict[str, Any] = {}
        self._features: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        with open(self._tiers_path, encoding="utf-8") as f:
            self._tiers = yaml.safe_load(f)
        with open(self._features_path, encoding="utf-8") as f:
            self._features = yaml.safe_load(f)

    @property
    def event_mechanisms(self) -> dict[str, dict[str, Any]]:
        """All event-triggered mechanism definitions."""
        return cast(dict[str, dict[str, Any]], self._tiers.get("event_triggered", {}))

    def evaluate(self, observables: dict[str, Any]) -> TriggerResult:
        """Evaluate all event triggers against observables.

        Parameters
        ----------
        observables : dict
            Current observable values. Keys are variable names
            (e.g., "dd_vel_SPY_5d", "settlement_fail_count").
            Values are numeric or boolean.

        Returns
        -------
        TriggerResult with activated mechanisms.
        """
        result = TriggerResult(observables_used=observables)
        event_mechs = self.event_mechanisms

        for name, definition in event_mechs.items():
            condition = definition.get("trigger_condition", "")
            if not condition:
                continue

            result.evaluated += 1
            try:
                activated = evaluate_condition(condition, observables)
            except (SyntaxError, IndexError, KeyError) as exc:
                result.errors.append(f"{name}: {exc}")
                continue

            if activated:
                # Enrich from mechanism_features.yaml
                feat_info = self._features.get(name, {})
                triggered = TriggeredMechanism(
                    name=name,
                    tier="event",
                    trigger_condition=condition,
                    event_type=definition.get("event_type", "unknown"),
                    description=definition.get("description", ""),
                    related_mechanisms=definition.get("related_mechanisms", []),
                    features=feat_info.get("features", []),
                    signal=feat_info.get("signal", ""),
                    k_state_direction=feat_info.get("k_state_direction", ""),
                    related_variables=feat_info.get("related_variables", []),
                    related_entities=feat_info.get("related_entities", []),
                    related_cases=feat_info.get("related_cases", []),
                    tags=feat_info.get("tags", []),
                )
                result.triggered.append(triggered)

        return result

    def evaluate_single(self, mechanism_name: str, observables: dict[str, Any]) -> bool:
        """Evaluate a single mechanism's trigger condition."""
        definition = self.event_mechanisms.get(mechanism_name, {})
        condition = definition.get("trigger_condition", "")
        if not condition:
            return False
        return evaluate_condition(condition, observables)

    def save_result(self, result: TriggerResult) -> Path:
        """Save trigger result to JSON."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = {
            "evaluated": result.evaluated,
            "activated": result.activation_count,
            "errors": result.errors,
            "triggered": [
                {
                    "name": m.name,
                    "event_type": m.event_type,
                    "trigger_condition": m.trigger_condition,
                    "related_mechanisms": m.related_mechanisms,
                    "features": m.features,
                    "k_state_direction": m.k_state_direction,
                    "related_variables": m.related_variables,
                }
                for m in result.triggered
            ],
            "cascade_candidates": result.related_mechanism_names(),
        }
        path = OUTPUT_DIR / "trigger_result.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        return cast(Path, path)


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> None:
    """Demo: evaluate triggers with sample observables."""
    engine = EventTriggerEngine()

    # Sample observables simulating a stress scenario
    sample_observables = {
        "dd_vel_SPY_5d": 0.04,
        "dd_vel_SPY_10d": 0.06,
        "rv_SPY_20d": 0.30,
        "rv_SPY_60d": 0.22,
        "rv_XLF_20d": 0.28,
        "haircut_change": 0.08,
        "settlement_fail_count": 2,
        "leverage_ratio": 15.0,
        "treasury_basis_spread": 3.5,
    }

    result = engine.evaluate(sample_observables)

    print(f"Evaluated: {result.evaluated} mechanisms")
    print(f"Activated: {result.activation_count}")
    print()

    for m in result.triggered:
        print(f"  ✓ {m.name}")
        print(f"    Condition: {m.trigger_condition}")
        print(f"    Event type: {m.event_type}")
        print(f"    K direction: {m.k_state_direction}")
        print(f"    Cascade → {m.related_mechanisms}")
        print()

    if result.errors:
        print(f"Errors: {result.errors}")


if __name__ == "__main__":
    main()
