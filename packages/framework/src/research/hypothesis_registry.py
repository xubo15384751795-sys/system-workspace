from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.schemas import ResearchHypothesis


DEFAULT_HYPOTHESES: tuple[ResearchHypothesis, ...] = (
    ResearchHypothesis(
        name="banking_duration_mismatch_signal",
        hypothesis="Rapid rate shock plus bank equity dispersion plus deposit pressure raises local M/K and compresses D.",
        mechanism_family="duration_loss_operator",
        required_proxies=("yield_curve_shock", "KRE", "KBE", "H8_deposits", "AOCI_proxy"),
        expected_horizon="20-90d",
        target_to_test="forward_20d_credit_stress_widening",
        failure_condition="Signal rises without bank equity dispersion, deposit stress, or credit/liquidity widening.",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        forbidden_claims=("predicts bank runs", "portfolio hedge instruction", "validated early warning"),
    ),
    ResearchHypothesis(
        name="policy_backstop_shadow_backflow",
        hypothesis="Policy backstop can restore D while increasing X if private losses are delayed rather than resolved.",
        mechanism_family="policy_backstop_operator",
        required_proxies=("central_bank_events", "facility_usage", "credit_spreads", "NFCI"),
        expected_horizon="20-180d",
        target_to_test="forward_60d_realized_vol_spike",
        failure_condition="Backstop improves D and X decays without later stress recurrence.",
        maturity=ClaimMaturityTag.PROXY_SUPPORTED,
        forbidden_claims=("policy eliminates risk", "validated timing signal"),
    ),
    ResearchHypothesis(
        name="low_vix_treasury_liquidity_gap",
        hypothesis="Treasury liquidity can worsen while VIX stays calm, creating hidden D/K fragility missed by VIX-only baselines.",
        mechanism_family="liquidity_evaporation_operator",
        required_proxies=("Treasury_depth", "MOVE", "OFR_FSI", "VIXCLS"),
        expected_horizon="5-60d",
        target_to_test="forward_20d_liquidity_stress_widening",
        failure_condition="Liquidity proxies do not add information over VIX/MOVE baselines.",
        maturity=ClaimMaturityTag.HYPOTHESIS,
        forbidden_claims=("beats VIX", "tradable alpha"),
    ),
)


class ResearchHypothesisRegistry:
    def __init__(self, hypotheses: tuple[ResearchHypothesis, ...] = DEFAULT_HYPOTHESES) -> None:
        self._hypotheses = {hypothesis.name: hypothesis for hypothesis in hypotheses}

    def all(self) -> tuple[ResearchHypothesis, ...]:
        return tuple(self._hypotheses.values())

    def get(self, name: str) -> ResearchHypothesis | None:
        return self._hypotheses.get(name)

    def register(self, hypothesis: ResearchHypothesis) -> None:
        self._hypotheses[hypothesis.name] = hypothesis

    def by_maturity(self, maturity: ClaimMaturityTag) -> tuple[ResearchHypothesis, ...]:
        return tuple(item for item in self._hypotheses.values() if item.maturity == maturity)
