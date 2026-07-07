from __future__ import annotations

import re
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Any

from pydantic import BaseModel, Field
import yaml

from nlp.extraction.schemas import ExtractedEntity, StructuralEventCard, VariableMapping


ROOT = _workspace_root()
MAPPING_RULES = ROOT / "Data" / "nlp" / "mapping_rules.yaml"
STRUCTURAL_VARIABLES = ("S", "A", "L", "V", "P", "tau")


class MappingVote(BaseModel):
    rule_id: str
    variable: str
    matched_text: str
    weight: float = 1.0
    reason: str


class MappingResult(BaseModel):
    variable_mapping: VariableMapping
    votes: list[MappingVote] = Field(default_factory=list)
    confidence_by_variable: dict[str, float] = Field(default_factory=dict)
    abstained: bool = False
    abstention_reason: str = ""


class VariableMapper:
    """Map structural NLP entities/events through labeling-function votes."""

    def __init__(self, rules_path: Path | None = None, *, min_vote_weight: float = 0.1) -> None:
        self.rules_path = rules_path or MAPPING_RULES
        self.rules = self._load_rules(self.rules_path)
        self.min_vote_weight = min_vote_weight

    def vote_entities(self, entities: list[ExtractedEntity]) -> list[MappingVote]:
        votes: list[MappingVote] = []
        entity_rules: dict[str, Any] = self.rules.get("entity_mapping", {})

        for entity in entities:
            if entity.variable_hint:
                for variable in entity.variable_hint:
                    votes.append(
                        MappingVote(
                            rule_id=f"entity_hint:{entity.type}",
                            variable=variable,
                            matched_text=entity.text,
                            weight=0.8,
                            reason=f"Entity extractor hinted {entity.type!r} maps to {variable}.",
                        )
                    )
                continue

            rule = entity_rules.get(entity.type, {})
            for variable in rule.get("variables", []):
                votes.append(
                    MappingVote(
                        rule_id=f"entity_rule:{entity.type}",
                        variable=variable,
                        matched_text=entity.text,
                        weight=float(rule.get("weight", 0.7)),
                        reason=str(rule.get("description", f"{entity.type} maps to {variable}.")),
                    )
                )
        return votes

    def vote_event(
        self,
        *,
        entities: list[ExtractedEntity],
        text: str = "",
        event_card: StructuralEventCard | None = None,
    ) -> list[MappingVote]:
        votes = self.vote_entities(entities)
        haystack = self._event_text(text=text, event_card=event_card)
        if not haystack.strip():
            return votes

        event_patterns: dict[str, Any] = self.rules.get("event_patterns", {})
        for pattern_name, rule in event_patterns.items():
            signal = str(rule.get("signal", ""))
            needles = [pattern_name.replace("_", " "), signal.replace("_", " ")]
            matched = next((needle for needle in needles if needle and needle.lower() in haystack.lower()), "")
            if not matched:
                continue
            for variable in rule.get("variables", []):
                votes.append(
                    MappingVote(
                        rule_id=f"event_pattern:{pattern_name}",
                        variable=variable,
                        matched_text=matched,
                        weight=float(rule.get("weight", 0.65)),
                        reason=str(rule.get("description", f"{pattern_name} suggests {variable}.")),
                    )
                )

        for variable, rules in _FALLBACK_LABELING_FUNCTIONS.items():
            for rule_id, pattern, weight, reason in rules:
                match = re.search(pattern, haystack, re.IGNORECASE)
                if match:
                    votes.append(
                        MappingVote(
                            rule_id=rule_id,
                            variable=variable,
                            matched_text=match.group(0),
                            weight=weight,
                            reason=reason,
                        )
                    )

        return votes

    def aggregate_votes(self, votes: list[MappingVote]) -> MappingResult:
        valid_votes = [
            vote
            for vote in votes
            if vote.variable in STRUCTURAL_VARIABLES and vote.weight >= self.min_vote_weight
        ]
        values: dict[str, list[str]] = {var: [] for var in STRUCTURAL_VARIABLES}
        weights: dict[str, float] = {var: 0.0 for var in STRUCTURAL_VARIABLES}
        total_weight = sum(vote.weight for vote in valid_votes)

        if not valid_votes or total_weight <= 0:
            return MappingResult(
                variable_mapping=VariableMapping(),
                votes=[],
                confidence_by_variable={},
                abstained=True,
                abstention_reason="No labeling function produced sufficient evidence.",
            )

        for vote in valid_votes:
            if vote.matched_text not in values[vote.variable]:
                values[vote.variable].append(vote.matched_text)
            weights[vote.variable] += vote.weight

        confidence_by_variable = {
            variable: round(min(0.95, weight / total_weight), 3)
            for variable, weight in weights.items()
            if weight > 0
        }
        return MappingResult(
            variable_mapping=VariableMapping(**values),
            votes=valid_votes,
            confidence_by_variable=confidence_by_variable,
            abstained=False,
        )

    def map_entities_with_votes(self, entities: list[ExtractedEntity]) -> MappingResult:
        return self.aggregate_votes(self.vote_entities(entities))

    def map_entities(self, entities: list[ExtractedEntity]) -> VariableMapping:
        return self.map_entities_with_votes(entities).variable_mapping

    def map_event_with_votes(
        self,
        *,
        entities: list[ExtractedEntity],
        text: str = "",
        event_card: StructuralEventCard | None = None,
    ) -> MappingResult:
        return self.aggregate_votes(self.vote_event(entities=entities, text=text, event_card=event_card))

    def map_event(
        self,
        *,
        entities: list[ExtractedEntity],
        text: str = "",
        event_card: StructuralEventCard | None = None,
    ) -> VariableMapping:
        return self.map_event_with_votes(entities=entities, text=text, event_card=event_card).variable_mapping

    def _event_text(self, *, text: str, event_card: StructuralEventCard | None) -> str:
        return " ".join(
            [
                text,
                event_card.event_name if event_card else "",
                " ".join(event_card.triggers if event_card else []),
                " ".join(event_card.liquidity_paths if event_card else []),
                event_card.visibility_shift if event_card else "",
            ]
        )

    def _load_rules(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"entity_mapping": {}, "event_patterns": {}}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Mapping rules must be a mapping: {path}")
        return data


def map_entities_to_variables(
    entities: list[ExtractedEntity],
    *,
    text: str = "",
    event_card: StructuralEventCard | None = None,
    rules_path: Path | None = None,
) -> VariableMapping:
    mapper = VariableMapper(rules_path=rules_path)
    if text or event_card:
        return mapper.map_event(entities=entities, text=text, event_card=event_card)
    return mapper.map_entities(entities)


def map_entities_to_result(
    entities: list[ExtractedEntity],
    *,
    text: str = "",
    event_card: StructuralEventCard | None = None,
    rules_path: Path | None = None,
) -> MappingResult:
    mapper = VariableMapper(rules_path=rules_path)
    if text or event_card:
        return mapper.map_event_with_votes(entities=entities, text=text, event_card=event_card)
    return mapper.map_entities_with_votes(entities)


_FALLBACK_LABELING_FUNCTIONS: dict[str, list[tuple[str, str, float, str]]] = {
    "S": [
        ("lf.subject.bank_actor", r"\b(depositor|investor|issuer|borrower|lender|bank|fund)\b", 0.45, "Actor term indicates a subject."),
    ],
    "A": [
        ("lf.anchor.valuation_terms", r"\b(anchor|valuation|book value|fair value|confidence|spread)\b", 0.55, "Anchor or valuation term indicates A."),
        ("lf.anchor.accounting_anchor", r"\b(held.?to.?maturity|accounting anchor|market.?value)\b", 0.6, "Accounting/market value anchor indicates A."),
    ],
    "L": [
        ("lf.liquidity.liquidation_terms", r"\b(liquidat\w*|forced sell\w*|fire sale|withdrawal|redemption|margin call)\b", 0.6, "Liquidity path term indicates L."),
        ("lf.liquidity.deposit_flow", r"\b(deposit outflow\w*|deposit flight|liquidity demand\w*)\b", 0.6, "Deposit/liquidity flow indicates L."),
    ],
    "V": [
        ("lf.visibility.disclosure_terms", r"\b(disclos\w*|visible|visibility|opacity|transparent|unrealized)\b", 0.55, "Visibility/disclosure term indicates V."),
    ],
    "P": [
        ("lf.power.backstop_terms", r"\b(backstop|guarantee|facility|intervention|policy|regulator)\b", 0.55, "Backstop or policy capacity indicates P."),
    ],
    "tau": [
        ("lf.latency.delay_terms", r"\b(delay|lag|latency|recognition|rollover|refinanc\w*)\b", 0.55, "Delay or rollover timing indicates tau."),
    ],
}
