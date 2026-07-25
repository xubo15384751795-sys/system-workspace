"""Execute Paper state machine definitions against indicator snapshots."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from caselab_context.paper_paths import paper_root
from caselab_context.regime_from_indicators import (
    _load_history,
    load_indicator_snapshot,
)

MACHINES_DIR = paper_root() / "90_Admin/Context Rules/state_machines"
PROCESSED_DIR = paper_root() / "data_pipeline/data/processed"


@dataclass
class MachineEvaluation:
    id: str
    canonical_name: str
    current_state: str
    previous_state: str | None
    transition: dict[str, Any] | None
    variables: dict[str, str]
    evidence: list[str] = field(default_factory=list)
    paper_model: str = ""
    linked_cases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "current_state": self.current_state,
            "previous_state": self.previous_state,
            "transition": self.transition,
            "variables": self.variables,
            "evidence": self.evidence,
            "paper_model": self.paper_model,
            "linked_cases": self.linked_cases,
        }


@lru_cache(maxsize=1)
def load_state_machines() -> list[dict[str, Any]]:
    if not MACHINES_DIR.exists():
        return []
    machines: list[dict[str, Any]] = []
    for path in sorted(MACHINES_DIR.glob("*.yml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("id"):
            machines.append(data)
    machines.sort(key=lambda item: int(item.get("priority") or 0), reverse=True)
    return machines


def _indicator_value(snapshot: dict[str, Any], name: str) -> float | None:
    row = snapshot.get(name) or {}
    value = row.get("value")
    return float(value) if value is not None else None


def _match_conditions(conditions: list[dict[str, Any]], snapshot: dict[str, Any]) -> bool:
    for cond in conditions:
        if cond.get("default"):
            return True
        indicator = cond.get("indicator")
        if not indicator:
            continue
        value = _indicator_value(snapshot, indicator)
        if value is None:
            return False
        if "gte" in cond and value < float(cond["gte"]):
            return False
        if "gt" in cond and value <= float(cond["gt"]):
            return False
        if "lte" in cond and value > float(cond["lte"]):
            return False
        if "lt" in cond and value >= float(cond["lt"]):
            return False
        if "eq" in cond and value != float(cond["eq"]):
            return False
    return True


def _resolve_state(machine: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str, list[str]]:
    states = machine.get("states") or {}
    for rule in machine.get("state_rules") or []:
        state_id = str(rule.get("state") or "")
        when = rule.get("when") or []
        if _match_conditions(when, snapshot):
            label = (states.get(state_id) or {}).get("label") or state_id
            evidence = [f"state={state_id} ({label})"]
            for cond in when:
                if cond.get("default"):
                    evidence.append("default_state_rule")
                    continue
                indicator = cond.get("indicator")
                if indicator:
                    value = _indicator_value(snapshot, indicator)
                    if value is not None:
                        evidence.append(f"{indicator}={value:.2f}")
            return state_id, evidence
    return "unknown", ["no_state_rule_matched"]


def _historical_snapshot(machine: dict[str, Any], lookback_days: int) -> dict[str, Any]:
    indicators = machine.get("indicators") or {}
    snapshot: dict[str, Any] = {}
    for name, meta in indicators.items():
        filename = meta.get("file")
        if not filename:
            continue
        history = _load_history(PROCESSED_DIR / filename, lookback=lookback_days + 5)
        if len(history) < lookback_days + 1:
            continue
        date, value = history[-(lookback_days + 1)]
        snapshot[name] = {"date": date, "value": value}
    return snapshot


def _map_variables(machine: dict[str, Any], state_id: str) -> dict[str, str]:
    variable_map = machine.get("variable_map") or {}
    return {var: str(levels.get(state_id) or "unknown") for var, levels in variable_map.items()}


def _latest_value(path: Path) -> dict[str, Any] | None:
    history = _load_history(path, lookback=1)
    if not history:
        return None
    date, value = history[-1]
    return {"date": date, "value": value}


def _machine_indicator_snapshot(
    machine: dict[str, Any],
    base_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge machine-specific indicators into a shared snapshot."""
    snap = dict(base_snapshot or {})
    for name, meta in (machine.get("indicators") or {}).items():
        if name in snap:
            continue
        filename = meta.get("file")
        if not filename:
            continue
        latest = _latest_value(PROCESSED_DIR / filename)
        if latest:
            snap[name] = latest
    return snap


def evaluate_machine(
    machine: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
) -> MachineEvaluation:
    snap = _machine_indicator_snapshot(machine, snapshot)
    current_state, evidence = _resolve_state(machine, snap)
    lookback = int(machine.get("transition_lookback_days") or 20)
    prior_snap = _historical_snapshot(machine, lookback)
    previous_state = None
    transition = None
    if prior_snap:
        previous_state, _ = _resolve_state(machine, prior_snap)
        if previous_state != current_state:
            transition = {
                "from": previous_state,
                "to": current_state,
                "lookback_days": lookback,
            }
            evidence.append(f"transition:{previous_state}->{current_state}")

    return MachineEvaluation(
        id=str(machine.get("id")),
        canonical_name=str(machine.get("canonical_name") or machine.get("id")),
        current_state=current_state,
        previous_state=previous_state,
        transition=transition,
        variables=_map_variables(machine, current_state),
        evidence=evidence,
        paper_model=str(machine.get("paper_model") or ""),
        linked_cases=[str(x) for x in (machine.get("linked_cases") or [])],
    )


def evaluate_world_state(
    *,
    machine_ids: list[str] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snap = snapshot or load_indicator_snapshot()
    as_of = ""
    for item in snap.values():
        if item.get("date"):
            as_of = max(as_of, str(item["date"])) if as_of else str(item["date"])

    evaluations: list[MachineEvaluation] = []
    for machine in load_state_machines():
        machine_id = str(machine.get("id"))
        if machine_ids and machine_id not in machine_ids:
            continue
        evaluations.append(evaluate_machine(machine, snap))

    return {
        "as_of": as_of,
        "machines": [item.to_dict() for item in evaluations],
    }


def get_machine(machine_id: str) -> dict[str, Any] | None:
    for machine in load_state_machines():
        if str(machine.get("id")) == machine_id:
            return machine
    return None
