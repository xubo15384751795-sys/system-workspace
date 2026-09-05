from __future__ import annotations

from src.research.schemas import ClaimMaturityTag
from src.research.schemas import FrontierVariable, MechanismComposition, StructuralMechanism
from src.research.structural_mechanism_library import StructuralMechanismLibrary
from src.research.variable_generator import FrontierVariableGenerator


COMPOSITION_TEMPLATES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "bank_duration_run_spiral",
        "banking_MDKX",
        ("duration_loss_operator", "deposit_run_operator", "policy_backstop_operator"),
        "Rate shock creates duration loss; confidence shock compresses deposit D; policy restores D but may leave X.",
    ),
    (
        "treasury_basis_liquidity_spiral",
        "treasury_liquidity_MDKX",
        ("basis_dislocation_operator", "dealer_balance_sheet_compression_operator", "liquidity_evaporation_operator"),
        "Basis dislocation consumes dealer capacity; market depth falls; K rises before broad volatility confirms.",
    ),
    (
        "ldi_collateral_policy_loop",
        "uk_rates_ldi_MDKX",
        ("collateral_spiral_operator", "liquidity_evaporation_operator", "policy_backstop_operator"),
        "Gilt drawdown triggers collateral pressure; liquidity evaporates; intervention changes D but not all X.",
    ),
    (
        "credit_carry_shadow_release",
        "credit_carry_MDKX",
        ("basis_dislocation_operator", "collateral_spiral_operator", "narrative_acceleration_operator"),
        "Carry crowding and downgrade curvature turn slow X into realized spread/liquidity stress.",
    ),
    (
        "fx_funding_swapline_relief_gap",
        "fx_funding_MDKX",
        ("basis_dislocation_operator", "policy_backstop_operator", "dealer_balance_sheet_compression_operator"),
        "Dollar basis stress improves with backstops while dealer capacity can remain compressed.",
    ),
    (
        "ai_capex_private_credit_refi_loop",
        "ai_capex_private_credit_MDKX",
        ("narrative_acceleration_operator", "basis_dislocation_operator", "collateral_spiral_operator"),
        "Narrative acceleration widens valuation mismatch; credit carry turns into refinancing curvature.",
    ),
)


class MechanismComposer:
    def __init__(
        self,
        mechanism_library: StructuralMechanismLibrary | None = None,
        variable_generator: FrontierVariableGenerator | None = None,
    ) -> None:
        self.mechanism_library = mechanism_library or StructuralMechanismLibrary()
        self.variable_generator = variable_generator or FrontierVariableGenerator()

    def compose_all(self) -> tuple[MechanismComposition, ...]:
        variables = self.variable_generator.generate_all()
        return tuple(self._compose(name, space, mechanisms, thesis, variables) for name, space, mechanisms, thesis in COMPOSITION_TEMPLATES)

    def _compose(
        self,
        name: str,
        state_space: str,
        mechanism_names: tuple[str, ...],
        thesis: str,
        variables: tuple[FrontierVariable, ...],
    ) -> MechanismComposition:
        mechanisms = tuple(item for item in (self.mechanism_library.get(mech) for mech in mechanism_names) if item is not None)
        generated = tuple(var.name for var in variables if var.local_state_space == state_space)[:8]
        return MechanismComposition(
            name=name,
            local_state_space=state_space,
            mechanism_names=mechanism_names,
            operator_sequence=_operators(mechanisms),
            generated_variable_names=generated,
            structure_path=_structure_path(state_space),
            research_thesis=thesis,
            maturity=_lowest_maturity(mechanisms),
        )


def _operators(mechanisms: tuple[StructuralMechanism, ...]) -> tuple[str, ...]:
    names: list[str] = []
    for mechanism in mechanisms:
        names.extend(mechanism.operator_names)
    return tuple(dict.fromkeys(names))


def _structure_path(state_space: str) -> tuple[str, ...]:
    return (
        f"{state_space}: variable generation",
        "local M/D/K/X mapping",
        "operator sequence composition",
        "candidate signal generation",
        "validation queue",
        "claim guard release",
    )


def _lowest_maturity(mechanisms: tuple[StructuralMechanism, ...]) -> ClaimMaturityTag:
    if not mechanisms:
        return ClaimMaturityTag.HYPOTHESIS
    order = {
        ClaimMaturityTag.FORBIDDEN: -1,
        ClaimMaturityTag.HYPOTHESIS: 0,
        ClaimMaturityTag.PROXY_SUPPORTED: 1,
        ClaimMaturityTag.CASE_SUPPORTED: 2,
        ClaimMaturityTag.OOS_VALIDATED: 3,
        ClaimMaturityTag.PORTFOLIO_VALIDATED: 4,
    }
    return min((item.maturity for item in mechanisms), key=lambda tag: order[tag])
