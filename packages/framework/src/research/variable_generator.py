from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.local_state_spaces import LocalStateSpaceRegistry
from src.research.schemas import FrontierVariable, LocalStateSpace


CHANNEL_CONSTRUCTIONS = {
    "M": "z(local_anchor_gap) + z(cross_proxy_divergence)",
    "D": "-z(funding_flexibility) - z(liquidity_access)",
    "K": "z(acceleration) + z(dispersion) + z(convexity_proxy)",
    "X": "z(hidden_load_proxy) + z(realization_latency)",
}


class FrontierVariableGenerator:
    """
    Generates candidate variables before validation.

    The generator is intentionally permissive: weak maturity tags do not block
    creation. Claim and validation controls are attached after generation.
    """

    def __init__(self, state_spaces: LocalStateSpaceRegistry | None = None) -> None:
        self.state_spaces = state_spaces or LocalStateSpaceRegistry()

    def generate_for_space(self, space: LocalStateSpace) -> tuple[FrontierVariable, ...]:
        variables: list[FrontierVariable] = []
        for channel, concepts in space.channels.items():
            for concept in concepts:
                variables.append(
                    FrontierVariable(
                        name=f"{space.name}_{concept}",
                        local_state_space=space.name,
                        channel=channel,
                        construction=CHANNEL_CONSTRUCTIONS.get(channel, "candidate public proxy transform"),
                        rationale=f"{concept} is mapped to {channel} inside {space.name}: {space.thesis}",
                        public_proxy_candidates=space.public_proxy_families,
                        maturity=min(space.maturity, ClaimMaturityTag.PROXY_SUPPORTED, key=lambda tag: _rank(tag)),
                        expected_horizon=_horizon_for_channel(channel),
                        failure_condition=f"{concept} does not improve explanation, case replay, or OOS tests over simpler public proxies.",
                    )
                )
        return tuple(variables)

    def generate_all(self) -> tuple[FrontierVariable, ...]:
        out: list[FrontierVariable] = []
        for space in self.state_spaces.all():
            out.extend(self.generate_for_space(space))
        return tuple(out)


def _horizon_for_channel(channel: str) -> str:
    if channel in {"M", "X"}:
        return "20-180d"
    if channel == "D":
        return "5-60d"
    return "5-20d"


def _rank(tag: ClaimMaturityTag) -> int:
    order = {
        ClaimMaturityTag.FORBIDDEN: -1,
        ClaimMaturityTag.HYPOTHESIS: 0,
        ClaimMaturityTag.PROXY_SUPPORTED: 1,
        ClaimMaturityTag.CASE_SUPPORTED: 2,
        ClaimMaturityTag.OOS_VALIDATED: 3,
        ClaimMaturityTag.PORTFOLIO_VALIDATED: 4,
    }
    return order[tag]
