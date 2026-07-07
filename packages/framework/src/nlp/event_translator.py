from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class NLPEventTranslator:
    """
    Converts structured NLP output into event_log rows that the operator algebra
    can consume.

    Input: list[dict] -- each dict can be:
      - case_library JSON (has event_patterns, variable_vector, vintage)
      - golden_event_card (has expected_variables, expected_triggers)
      - raw tagged text (has entities, events from any extractor)

    Output: pd.DataFrame with columns:
      [date, event_type, channel, intensity, actor, description]
    """

    def __init__(self, signal_map: dict[str, str], event_rules: dict[str, Any]) -> None:
        self.signal_map: dict[str, str] = {k.lower(): v.upper() for k, v in signal_map.items()}
        self.event_rules: dict[str, Any] = event_rules

    @classmethod
    def from_mapping_rules(cls, path: str | Path) -> NLPEventTranslator:
        with open(path, "r", encoding="utf-8") as handle:
            rules = yaml.safe_load(handle)
        return cls(
            signal_map=rules.get("signal_to_operator", {}),
            event_rules=rules.get("event_patterns", {}),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(self, texts: list[dict]) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for item in texts:
            rows.extend(self._item_to_rows(item))
        if not rows:
            return pd.DataFrame(
                columns=["date", "event_type", "channel", "intensity", "actor", "description"]
            )
        return pd.DataFrame.from_records(rows)

    def translate_texts_only(self, texts: list[str], run_date: str = "", actor: str = "") -> pd.DataFrame:
        """Convenience: translate raw text dicts to event rows."""
        dicts = [{"text": t, "run_date": run_date, "actor": actor} for t in texts]
        return self.translate(dicts)

    # ------------------------------------------------------------------
    # Internal dispatch by item shape
    # ------------------------------------------------------------------

    def _item_to_rows(self, item: dict) -> list[dict[str, Any]]:
        if "event_patterns" in item:
            return self._from_case_library(item)
        if "expected_variables" in item or "expected_triggers" in item:
            return self._from_event_card(item)
        if "entities" in item or "events" in item:
            return self._from_tagged_text(item)
        return []

    # ------------------------------------------------------------------
    # Source A: case_library JSON
    # ------------------------------------------------------------------

    def _from_case_library(self, case: dict) -> list[dict[str, Any]]:
        date = case.get("vintage", "")
        actor = self._primary_actor(case)
        variable_vector = case.get("variable_vector", {})
        rows: list[dict[str, Any]] = []
        for pattern in case.get("event_patterns", []):
            rule = self.event_rules.get(pattern) if isinstance(pattern, str) else pattern
            if rule is None:
                rows.append(self._raw_event_row(pattern, date, actor, variable_vector, case))
                continue
            signal = rule.get("signal", "")
            operator = self.signal_map.get(signal, signal.upper())
            if not operator:
                continue
            is_recovery = "P" in rule.get("variables", [])
            rows.append(
                {
                    "date": date,
                    "event_type": operator,
                    "channel": self._primary_channel(rule.get("variables", []), variable_vector),
                    "intensity": self._intensity(rule, variable_vector, is_recovery=is_recovery),
                    "actor": actor,
                    "description": f"{pattern} -- {case.get('case_name', '')}".strip(" -"),
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Source B: golden_event_card
    # ------------------------------------------------------------------

    def _from_event_card(self, card: dict) -> list[dict[str, Any]]:
        date = card.get("event_date", card.get("vintage", ""))
        actor = card.get("actor", card.get("entity", ""))
        variable_vector = card.get("variable_vector", {})
        rows: list[dict[str, Any]] = []
        for expected in card.get("expected_variables", []):
            signal = expected.get("signal", "")
            operator = self.signal_map.get(signal, signal.upper())
            if not operator:
                continue
            rows.append(
                {
                    "date": date,
                    "event_type": operator,
                    "channel": self._primary_channel([], variable_vector),
                    "intensity": expected.get("intensity", 0.65),
                    "actor": actor,
                    "description": f"{signal} -- expected trigger",
                }
            )
        for trigger in card.get("expected_triggers", []):
            if isinstance(trigger, str):
                operator = self.signal_map.get(trigger, trigger.upper())
                rows.append(
                    {
                        "date": date,
                        "event_type": operator,
                        "channel": "D",
                        "intensity": 0.65,
                        "actor": actor,
                        "description": f"{trigger} -- expected trigger",
                    }
                )
            elif isinstance(trigger, dict):
                signal = trigger.get("signal", trigger.get("event_type", ""))
                operator = self.signal_map.get(signal, signal.upper())
                rows.append(
                    {
                        "date": date,
                        "event_type": operator,
                        "channel": trigger.get("channel", "D"),
                        "intensity": trigger.get("intensity", 0.65),
                        "actor": actor,
                        "description": trigger.get("description", f"{signal} -- expected trigger"),
                    }
                )
        return rows

    # ------------------------------------------------------------------
    # Source C: raw tagged text
    # ------------------------------------------------------------------

    def _from_tagged_text(self, item: dict) -> list[dict[str, Any]]:
        date = item.get("date", item.get("run_date", ""))
        actor = item.get("actor", "")
        rows: list[dict[str, Any]] = []
        for entity in item.get("entities", []):
            if isinstance(entity, dict) and entity.get("type") == "event":
                signal = entity.get("subtype", entity.get("name", ""))
                operator = self.signal_map.get(signal, signal.upper())
                rows.append(
                    {
                        "date": date,
                        "event_type": operator,
                        "channel": entity.get("channel", "D"),
                        "intensity": entity.get("confidence", 0.65),
                        "actor": entity.get("name", actor),
                        "description": entity.get("text", f"Tagged: {signal}"),
                    }
                )
        for event in item.get("events", []):
            if isinstance(event, str):
                operator = self.signal_map.get(event, event.upper())
                rows.append(
                    {
                        "date": date,
                        "event_type": operator,
                        "channel": "D",
                        "intensity": 0.65,
                        "actor": actor,
                        "description": f"Tagged: {event}",
                    }
                )
            elif isinstance(event, dict):
                signal = event.get("signal", event.get("event_type", ""))
                operator = self.signal_map.get(signal, signal.upper())
                rows.append(
                    {
                        "date": date,
                        "event_type": operator,
                        "channel": event.get("channel", "D"),
                        "intensity": event.get("intensity", event.get("confidence", 0.65)),
                        "actor": event.get("actor", actor),
                        "description": event.get("description", f"Tagged: {signal}"),
                    }
                )
        return rows

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _primary_actor(self, case: dict) -> str:
        return case.get("actor", case.get("primary_entity", case.get("case_name", "")))

    def _primary_channel(
        self, variables: list[str], variable_vector: dict
    ) -> str:
        """Infer primary channel from variable names or vector keys."""
        channel_hints = {
            "D": {"D", "dof", "degrees_of_freedom", "tau"},
            "M": {"M", "mismatch", "anchor_gap"},
            "K": {"K", "curvature", "convexity"},
            "X": {"X", "shadow", "hidden"},
        }
        # 1. Check explicit variables list
        for ch, hints in channel_hints.items():
            if hints & set(variables):
                return ch
        # 2. Check variable_vector keys
        vv_keys = set(variable_vector.keys())
        for ch, hints in channel_hints.items():
            if hints & vv_keys:
                return ch
        return "D"  # default: degrees-of-freedom channel

    def _intensity(
        self,
        rule: dict,
        variable_vector: dict,
        is_recovery: bool = False,
    ) -> float:
        """Derive intensity from rule weight and tau multiplier.

        tau in [0,1]: higher tau = more latency = lower immediate intensity.
        Recovery operators (P variable present) get lower base intensity since
        they expand rather than compress.
        """
        base = float(rule.get("weight", 0.65))
        tau = float(variable_vector.get("tau", 0.5))
        if "tau" in rule.get("variables", []) or "tau" in variable_vector:
            tau_mult = 1.0 + (1.0 - tau) * 0.5
        else:
            tau_mult = 1.0
        raw = base * tau_mult
        if is_recovery:
            raw *= 0.7
        return round(raw, 3)

    def _raw_event_row(
        self,
        pattern: str | dict,
        date: str,
        actor: str,
        variable_vector: dict,
        case: dict,
    ) -> dict[str, Any]:
        """Fallback when pattern not found in event_rules."""
        if isinstance(pattern, dict):
            signal = pattern.get("signal", pattern.get("event_type", ""))
            operator = self.signal_map.get(signal, signal.upper())
            return {
                "date": pattern.get("date", date),
                "event_type": operator,
                "channel": pattern.get("channel", "D"),
                "intensity": pattern.get("intensity", 0.65),
                "actor": pattern.get("actor", actor),
                "description": pattern.get("description", f"{signal} -- {case.get('case_name', '')}"),
            }
        operator = self.signal_map.get(pattern, pattern.upper())
        return {
            "date": date,
            "event_type": operator,
            "channel": "D",
            "intensity": 0.65,
            "actor": actor,
            "description": f"{pattern} -- {case.get('case_name', '')}",
        }
