from __future__ import annotations

from dataclasses import dataclass

from src.research.schemas import ClaimMaturityTag
from src.operators.operator_registry import build_default_operator_registry
from src.operators.operator_schema import OperatorSequence, OperatorStep
from src.research.candidate_signal_factory import CandidateSignalFactory
from src.research.schemas import CandidateSignal, ScenarioPathResult


DEFAULT_INITIAL_STATE = {"M": 0.2, "D": 0.1, "K": 0.2, "X": 0.2}


@dataclass(frozen=True)
class ScenarioTemplate:
    name: str
    event_type: str
    path: tuple[str, ...]
    operators: tuple[str, ...]
    proxies_to_watch: tuple[str, ...]
    missing_data: tuple[str, ...]
    candidate_signal_name: str
    maturity: ClaimMaturityTag = ClaimMaturityTag.HYPOTHESIS


DEFAULT_SCENARIOS: tuple[ScenarioTemplate, ...] = (
    ScenarioTemplate(
        name="Fed cuts while credit stress rises",
        event_type="generic_systemic_stress",
        path=("rate cut", "credit spread widening", "shadow backflow"),
        operators=("RATE_CUT", "BASIS_DISLOCATION", "OFF_BALANCE_SHEET_SHIFT"),
        proxies_to_watch=("DFF", "BAMLH0A0HYM2", "NFCI", "STLFSI4"),
        missing_data=("dealer_inventory", "private_funding_terms"),
        candidate_signal_name="policy_backstop_shadow_backflow",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
    ),
    ScenarioTemplate(
        name="Treasury liquidity worsens while VIX stays low",
        event_type="generic_systemic_stress",
        path=("dealer capacity drop", "liquidity withdrawal", "volatility delayed"),
        operators=("DEALER_CAPACITY_DROP", "LIQUIDITY_WITHDRAWAL", "VOL_SURFACE_KINK"),
        proxies_to_watch=("Treasury_depth", "OFR_FSI", "MOVE", "VIXCLS"),
        missing_data=("realtime_order_book_depth",),
        candidate_signal_name="low_vix_treasury_liquidity_gap",
    ),
    ScenarioTemplate(
        name="Bank deposits stabilize but unrealized losses remain",
        event_type="banking_fragility",
        path=("deposit guarantee", "duration loss remains", "confidence repair incomplete"),
        operators=("DEPOSIT_GUARANTEE", "BASIS_DISLOCATION", "DEPOSIT_RUN"),
        proxies_to_watch=("H8_deposits", "KRE", "KBE", "AOCI_proxy", "yield_curve_shock"),
        missing_data=("insured_uninsured_deposit_mix", "bank_level_htm_marks"),
        candidate_signal_name="banking_duration_mismatch_signal",
    ),
    ScenarioTemplate(
        name="Policy backstop restores D but increases X",
        event_type="generic_systemic_stress",
        path=("policy backstop", "visible D relief", "shadow load delayed"),
        operators=("POLICY_BACKSTOP", "LIQUIDITY_FACILITY", "OFF_BALANCE_SHEET_SHIFT"),
        proxies_to_watch=("central_bank_events", "facility_usage", "NFCI", "credit_spreads"),
        missing_data=("private_loss_transfer",),
        candidate_signal_name="policy_backstop_shadow_backflow",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
    ),
)


class ScenarioPathGenerator:
    def __init__(self, candidate_factory: CandidateSignalFactory | None = None) -> None:
        self.registry = build_default_operator_registry()
        self.candidate_factory = candidate_factory or CandidateSignalFactory()

    def templates(self) -> tuple[ScenarioTemplate, ...]:
        return DEFAULT_SCENARIOS

    def generate(
        self,
        template_name: str,
        initial_state: dict[str, float] | None = None,
    ) -> ScenarioPathResult:
        template = self._template(template_name)
        state = initial_state or DEFAULT_INITIAL_STATE
        steps = []
        for name in template.operators:
            operator = self.registry.get(name)
            if operator is not None:
                steps.append(OperatorStep(operator=operator, intensity=1.0, metadata={"scenario": template.name}))
        sequence = OperatorSequence.from_steps(steps)
        final_state, trace = sequence.apply(state)
        trajectory = tuple(entry.after for entry in trace)
        first_break = _first_break_channel(trajectory)
        candidate = self._candidate(template.candidate_signal_name)
        return ScenarioPathResult(
            name=template.name,
            maturity=template.maturity,
            operator_sequence=tuple(step.operator.name for step in steps),
            scenario_path=template.path,
            initial_state=state,
            final_state=final_state,
            trajectory=trajectory,
            which_channel_breaks_first=first_break,
            proxies_to_watch=template.proxies_to_watch,
            missing_data=template.missing_data,
            observability_classification="research_scenario",
            allowed_claims=(
                "scenario path hypothesis",
                "operator-sequence mechanism candidate",
                "candidate exposure implication requiring portfolio validation",
            ),
            forbidden_claims=("validated prediction", "hedge fund alpha", "portfolio instruction"),
            tradable_hypothesis_candidate=_tradable_candidate(candidate),
        )

    def _template(self, name: str) -> ScenarioTemplate:
        for template in DEFAULT_SCENARIOS:
            if template.name == name:
                return template
        known = ", ".join(template.name for template in DEFAULT_SCENARIOS)
        raise KeyError(f"Unknown scenario {name!r}. Known scenarios: {known}")

    def _candidate(self, name: str) -> CandidateSignal | None:
        hypothesis = self.candidate_factory.registry.get(name)
        if hypothesis is None:
            return None
        return self.candidate_factory.from_hypothesis(hypothesis)


def _first_break_channel(trajectory: tuple[dict[str, float], ...] | tuple[object, ...]) -> str | None:
    thresholds = {"M": 0.8, "D": -0.65, "K": 0.65, "X": 0.65}
    for row in trajectory:
        values = dict(row)
        if values.get("D", 0.0) <= thresholds["D"]:
            return "D"
        for channel in ("M", "K", "X"):
            if values.get(channel, 0.0) >= thresholds[channel]:
                return channel
    return None


def _tradable_candidate(candidate: CandidateSignal | None) -> str:
    if candidate is None:
        return "No candidate signal attached; mechanism remains research-only."
    return (
        f"{candidate.name}: candidate exposure implication only; "
        f"test {candidate.target_to_test} over {candidate.expected_horizon} before any portfolio use."
    )
