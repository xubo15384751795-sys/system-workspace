"""Unified mechanism resolver — three-tier activation.

READS: mechanism_tiers.yaml, mechanism_features.yaml,
       mapping_rules.yaml (mechanism_mapping section)
WRITES: Output/state/caselab/resolved_mechanisms/ only

Resolves which mechanisms are active given current market state,
using three activation tiers:
  1. Signal — continuous features from mechanism_features.yaml
  2. Event  — discrete triggers from mechanism_tiers.yaml
  3. Knowledge — narrative/case context (passthrough)

Feeds activated mechanisms into causal_graph.resolve_event_causal()
for M/D/K/X impact propagation.
"""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from .causal_graph import PropagationResult, resolve_event_causal
from .event_trigger import EventTriggerEngine, TriggerResult

DATA_DIR = WorkspacePaths.discover().root / "Data" / "nlp" / "caselab_training"
MAPPING_RULES = WorkspacePaths.discover().root / "Data" / "nlp" / "mapping_rules.yaml"
OUTPUT_DIR = WorkspacePaths.discover().root / "Output" / "state" / "caselab" / "resolved_mechanisms"


@dataclass
class ResolvedMechanism:
    """A mechanism resolved to be active."""
    name: str
    tier: str                          # signal | event | knowledge
    activation_reason: str
    features: list[str]
    signal: str
    k_state_direction: str
    related_variables: list[str]
    related_entities: list[str]
    related_cases: list[str]
    tags: list[str]
    # Event tier only
    trigger_condition: str = ""
    event_type: str = ""
    # Causal propagation (filled by resolve_causal)
    causal_result: PropagationResult | None = None


@dataclass
class ResolverResult:
    """Full resolution output."""
    signal_activated: list[ResolvedMechanism] = field(default_factory=list)
    event_activated: list[ResolvedMechanism] = field(default_factory=list)
    knowledge_context: list[ResolvedMechanism] = field(default_factory=list)
    trigger_result: TriggerResult | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def all_active(self) -> list[ResolvedMechanism]:
        return self.signal_activated + self.event_activated

    @property
    def total_activated(self) -> int:
        return len(self.signal_activated) + len(self.event_activated)

    def mechanism_names(self) -> list[str]:
        return [m.name for m in self.all_active]

    def related_mechanism_names(self) -> list[str]:
        """Cascade candidates from event-triggered mechanisms."""
        names: set[str] = set()
        for m in self.event_activated:
            if m.trigger_condition:
                # Get related mechanisms from tiers definition
                names.update(m.tags)  # tags serve as proxy
        return sorted(names)

    def summary(self) -> dict[str, Any]:
        return {
            "signal_count": len(self.signal_activated),
            "event_count": len(self.event_activated),
            "knowledge_count": len(self.knowledge_context),
            "total_activated": self.total_activated,
            "signal_mechanisms": [m.name for m in self.signal_activated],
            "event_mechanisms": [m.name for m in self.event_activated],
            "errors": self.errors,
        }


class MechanismResolver:
    """Resolve active mechanisms across all three tiers.

    Usage:
        resolver = MechanismResolver()

        # Tier 1: Signal — provide market features
        # (features dict maps feature names to current values)
        result = resolver.resolve(
            market_features={"rv_SPY_20d": 0.30, "ratio_HYG_TLT": 0.45},
            observables={"dd_vel_SPY_5d": 0.04, "rv_SPY_20d": 0.30},
            narrative_keywords=["liquidity", "spiral", "margin"],
        )

        for m in result.all_active:
            print(f"[{m.tier}] {m.name}: {m.activation_reason}")
    """

    def __init__(
        self,
        tiers_path: Path | None = None,
        features_path: Path | None = None,
        mapping_rules_path: Path | None = None,
    ):
        self._features_path = features_path or DATA_DIR / "mechanism_features.yaml"
        self._mapping_rules_path = mapping_rules_path or MAPPING_RULES
        self._event_engine = EventTriggerEngine(tiers_path=tiers_path)

        # Load data
        self._features: dict[str, Any] = {}
        self._mechanism_mapping: dict[str, Any] = {}
        self._tiers: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        with open(self._features_path, encoding="utf-8") as f:
            self._features = yaml.safe_load(f)

        if self._mapping_rules_path.exists():
            with open(self._mapping_rules_path, encoding="utf-8") as f:
                rules = yaml.safe_load(f) or {}
            self._mechanism_mapping = rules.get("mechanism_mapping", {})

        tiers_path = self._event_engine._tiers_path
        with open(tiers_path, encoding="utf-8") as f:
            self._tiers = yaml.safe_load(f)

    # ── Tier 1: Signal activation ────────────────────────────────────────

    def _resolve_signal(
        self,
        market_features: dict[str, float],
        threshold: float = 0.5,
    ) -> list[ResolvedMechanism]:
        """Activate mechanisms whose features exceed thresholds.

        A mechanism is activated if at least one of its features
        has a value in market_features that suggests stress
        (absolute value above threshold for ratios, or above
        threshold for volatility measures).
        """
        activated: list[ResolvedMechanism] = []
        signal_mechanisms = self._tiers.get("signal_triggered", [])

        for name in signal_mechanisms:
            info = self._features.get(name, {})
            features = info.get("features", [])
            if not features:
                continue

            matched_features: list[str] = []
            for feat in features:
                val = market_features.get(feat)
                if val is None:
                    continue
                # Ratios: check deviation from 1.0
                if feat.startswith("ratio_"):
                    if abs(val - 1.0) > threshold * 0.5:
                        matched_features.append(feat)
                # Correlations: check deviation from 0
                elif feat.startswith("corr_"):
                    if abs(val) > threshold:
                        matched_features.append(feat)
                # Volatility: check absolute level
                elif feat.startswith("rv_") or feat.startswith("dd_vel_"):
                    if val > threshold * 0.5:
                        matched_features.append(feat)
                # Other features: generic threshold
                else:
                    if abs(val) > threshold:
                        matched_features.append(feat)

            if matched_features:
                activated.append(ResolvedMechanism(
                    name=name,
                    tier="signal",
                    activation_reason=f"Features triggered: {', '.join(matched_features)}",
                    features=features,
                    signal=info.get("signal", ""),
                    k_state_direction=info.get("k_state_direction", ""),
                    related_variables=info.get("related_variables", []),
                    related_entities=info.get("related_entities", []),
                    related_cases=info.get("related_cases", []),
                    tags=info.get("tags", []),
                ))

        return activated

    # ── Tier 2: Event activation ─────────────────────────────────────────

    def _resolve_event(self, observables: dict[str, Any]) -> tuple[list[ResolvedMechanism], TriggerResult]:
        """Activate mechanisms whose trigger conditions are met."""
        trigger_result = self._event_engine.evaluate(observables)
        activated: list[ResolvedMechanism] = []

        for triggered in trigger_result.triggered:
            activated.append(ResolvedMechanism(
                name=triggered.name,
                tier="event",
                activation_reason=f"Trigger: {triggered.trigger_condition}",
                features=triggered.features,
                signal=triggered.signal,
                k_state_direction=triggered.k_state_direction,
                related_variables=triggered.related_variables,
                related_entities=triggered.related_entities,
                related_cases=triggered.related_cases,
                tags=triggered.tags,
                trigger_condition=triggered.trigger_condition,
                event_type=triggered.event_type,
            ))

        return activated, trigger_result

    # ── Tier 3: Knowledge context ────────────────────────────────────────

    def _resolve_knowledge(
        self,
        narrative_keywords: list[str] | None = None,
    ) -> list[ResolvedMechanism]:
        """Return knowledge mechanisms relevant to current narrative.

        Knowledge mechanisms are always "available" — they're filtered
        by narrative keyword overlap to keep the context manageable.
        """
        if not narrative_keywords:
            return []

        activated: list[ResolvedMechanism] = []
        knowledge_mechanisms = self._tiers.get("knowledge_only", {})
        kw_set = set(k.lower() for k in narrative_keywords)

        for name, info in knowledge_mechanisms.items():
            # Check if any tags overlap with narrative keywords
            role = info.get("role", "").lower()
            domain = info.get("domain", "").lower()
            feat_info = self._features.get(name, {})
            tags = [t.lower() for t in feat_info.get("tags", [])]

            tag_overlap = kw_set.intersection(tags)
            role_words = set(role.split())
            role_overlap = kw_set.intersection(role_words)

            if tag_overlap or role_overlap or domain in kw_set:
                activated.append(ResolvedMechanism(
                    name=name,
                    tier="knowledge",
                    activation_reason=f"Keyword match: {tag_overlap or role_overlap or domain}",
                    features=feat_info.get("features", []),
                    signal=feat_info.get("signal", ""),
                    k_state_direction=feat_info.get("k_state_direction", ""),
                    related_variables=feat_info.get("related_variables", []),
                    related_entities=feat_info.get("related_entities", []),
                    related_cases=feat_info.get("related_cases", []),
                    tags=feat_info.get("tags", []),
                ))

        return activated

    # ── Unified resolve ──────────────────────────────────────────────────

    def resolve(
        self,
        market_features: dict[str, float] | None = None,
        observables: dict[str, Any] | None = None,
        narrative_keywords: list[str] | None = None,
        feature_threshold: float = 0.5,
    ) -> ResolverResult:
        """Resolve all active mechanisms across three tiers.

        Parameters
        ----------
        market_features : dict
            Current market feature values for signal activation.
        observables : dict
            Observable values for event trigger evaluation.
        narrative_keywords : list
            Keywords for knowledge mechanism filtering.
        feature_threshold : float
            Threshold for signal activation.

        Returns
        -------
        ResolverResult with all activated mechanisms.
        """
        result = ResolverResult()

        # Tier 1: Signal
        if market_features:
            result.signal_activated = self._resolve_signal(
                market_features, threshold=feature_threshold,
            )

        # Tier 2: Event
        if observables:
            result.event_activated, result.trigger_result = self._resolve_event(observables)

        # Tier 3: Knowledge
        result.knowledge_context = self._resolve_knowledge(narrative_keywords)

        return result

    # ── Causal propagation ───────────────────────────────────────────────

    def resolve_causal(
        self,
        entity_env: dict[str, Any],
        resolver_result: ResolverResult,
        k_level: float = 0.5,
    ) -> dict[str, Any]:
        """Propagate activated mechanisms through the causal graph.

        Takes the resolved mechanisms and feeds their related_variables
        into causal_graph.resolve_event_causal() to compute M/D/K/X
        impact deltas.

        Parameters
        ----------
        entity_env : dict
            Entity environment from entity_environments.json.
        resolver_result : ResolverResult
            Output from resolve().
        k_level : float
            Current System K level.

        Returns
        -------
        Combined causal propagation result.
        """
        # Collect all related variables from activated mechanisms
        all_variables: list[str] = []
        for mech in resolver_result.all_active:
            all_variables.extend(mech.related_variables)
        unique_variables = list(dict.fromkeys(all_variables))  # preserve order, dedupe

        if not unique_variables:
            return {
                "entity_id": entity_env.get("entity_id"),
                "activated_mechanisms": resolver_result.mechanism_names(),
                "propagation_paths": [],
                "mdx_delta": {"M": 0, "K": 0, "D": 0, "X": 0},
                "note": "No variables to propagate",
            }

        # Determine impact level based on activation tier
        # Event-triggered = higher base impact (discrete stress)
        # Signal-triggered = moderate base impact (continuous)
        event_count = len(resolver_result.event_activated)
        signal_count = len(resolver_result.signal_activated)
        base_impact = min(1.0, 0.3 + event_count * 0.15 + signal_count * 0.05)

        causal_result = resolve_event_causal(
            entity_env=entity_env,
            event_variables=unique_variables,
            event_impact=base_impact,
            k_level=k_level,
        )

        # Attach mechanism metadata
        causal_result["activated_mechanisms"] = resolver_result.mechanism_names()
        causal_result["activation_summary"] = resolver_result.summary()
        causal_result["event_activated"] = [m.name for m in resolver_result.event_activated]
        causal_result["signal_activated"] = [m.name for m in resolver_result.signal_activated]

        return causal_result

    # ── Output ───────────────────────────────────────────────────────────

    def save_result(self, result: ResolverResult) -> Path:
        """Save resolver result to JSON."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output = {
            "summary": result.summary(),
            "signal_activated": [
                {
                    "name": m.name,
                    "tier": m.tier,
                    "activation_reason": m.activation_reason,
                    "features": m.features,
                    "k_state_direction": m.k_state_direction,
                    "related_variables": m.related_variables,
                }
                for m in result.signal_activated
            ],
            "event_activated": [
                {
                    "name": m.name,
                    "tier": m.tier,
                    "trigger_condition": m.trigger_condition,
                    "event_type": m.event_type,
                    "related_mechanisms": m.tags,
                    "related_variables": m.related_variables,
                }
                for m in result.event_activated
            ],
            "knowledge_context": [
                {"name": m.name, "tier": m.tier, "activation_reason": m.activation_reason}
                for m in result.knowledge_context
            ],
        }
        path = OUTPUT_DIR / "resolver_result.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        return cast(Path, path)


# ── CLI ─────────────────────────────────────────────────────────────────

def main() -> None:
    """Demo: three-tier mechanism resolution."""
    resolver = MechanismResolver()

    # Simulate a stress scenario
    market_features = {
        "rv_SPY_20d": 0.30,
        "rv_SPY_60d": 0.22,
        "rv_XLF_20d": 0.28,
        "rv_TLT_20d": 0.18,
        "corr_SPY_TLT_60d": -0.65,
        "corr_SPY_HYG_60d": 0.82,
        "corr_HYG_TLT_60d": -0.70,
        "ratio_HYG_TLT": 0.42,
        "ratio_XLF_SPY": 0.88,
        "ratio_SMH_SPY": 1.35,
        "ratio_QQQ_SPY": 1.12,
        "dd_vel_SPY_5d": 0.04,
        "dd_vel_SPY_10d": 0.06,
        "dd_vel_XLF_5d": 0.05,
        "sector_dispersion_20d": 0.18,
        "UUP_level": 103.5,
        "corr_SPY_UUP_60d": -0.55,
        "ratio_SLV_GLD": 0.068,
        "corr_SPY_GLD_60d": -0.30,
        "ratio_IWM_SPY": 0.85,
        "ratio_QQQ_IWM": 1.32,
    }

    observables = {
        "dd_vel_SPY_5d": 0.04,
        "rv_SPY_20d": 0.30,
        "haircut_change": 0.08,
        "settlement_fail_count": 2,
        "leverage_ratio": 15.0,
        "treasury_basis_spread": 3.5,
    }

    narrative_keywords = [
        "liquidity", "margin", "credit", "spiral", "forced", "selling",
        "collateral", "leverage", "crisis", "contagion",
    ]

    result = resolver.resolve(
        market_features=market_features,
        observables=observables,
        narrative_keywords=narrative_keywords,
    )

    print("=" * 60)
    print("THREE-TIER MECHANISM RESOLUTION")
    print("=" * 60)
    print()

    print(f"Tier 1 (Signal):   {len(result.signal_activated)} activated")
    for m in result.signal_activated:
        print(f"  ✓ {m.name}")
        print(f"    {m.activation_reason}")
    print()

    print(f"Tier 2 (Event):    {len(result.event_activated)} activated")
    for m in result.event_activated:
        print(f"  ✓ {m.name}")
        print(f"    Condition: {m.trigger_condition}")
    print()

    print(f"Tier 3 (Knowledge): {len(result.knowledge_context)} in context")
    for m in result.knowledge_context:
        print(f"  ○ {m.name}")
    print()

    print(f"Total activated: {result.total_activated}")
    print(f"Summary: {result.summary()}")


if __name__ == "__main__":
    main()
