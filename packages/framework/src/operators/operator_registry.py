from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.operators.operator_schema import StructuralOperator


@dataclass
class StructuralOperatorRegistry:
    operators: dict[str, StructuralOperator] = field(default_factory=dict)
    enabled_families: set[str] | None = None

    def __post_init__(self) -> None:
        self.operators = {name.upper(): op for name, op in self.operators.items()}
        self._alias_index = self._build_alias_index()

    def get(self, name: str) -> StructuralOperator | None:
        key = _normalize(name)
        op_name = self._alias_index.get(key, key)
        operator = self.operators.get(op_name)
        if operator is None:
            return None
        if self.enabled_families is not None and operator.family not in self.enabled_families:
            return None
        return operator

    def all(self) -> list[StructuralOperator]:
        operators = list(self.operators.values())
        if self.enabled_families is None:
            return operators
        return [op for op in operators if op.family in self.enabled_families]

    def intervention_ops(self) -> list[StructuralOperator]:
        return [op for op in self.all() if op.recovery]

    def resolve_event(self, event: Mapping[str, Any]) -> StructuralOperator | None:
        text = _event_text(event)
        normalized_text = _normalize(text)
        for token in _candidate_tokens(event):
            operator = self.get(token)
            if operator is not None:
                return operator
        for alias, name in sorted(self._alias_index.items(), key=lambda item: len(item[0]), reverse=True):
            if alias and alias in normalized_text:
                return self.get(name)
        return self._heuristic_resolve(normalized_text)

    def _build_alias_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for operator in self.operators.values():
            names = (operator.name, *operator.aliases)
            for name in names:
                index[_normalize(name)] = operator.name
        return index

    def _heuristic_resolve(self, text: str) -> StructuralOperator | None:
        if not text:
            return None
        if "QE" in text or "QUANTITATIVE_EASING" in text:
            return self.get("QE")
        if "DEPOSIT" in text and ("GUARANTEE" in text or "INSURANCE" in text):
            return self.get("DEPOSIT_GUARANTEE")
        if "LIQUIDITY" in text and ("FACILITY" in text or "BACKSTOP" in text or "INJECT" in text):
            return self.get("LIQUIDITY_FACILITY")
        if "BACKSTOP" in text or "RESCUE" in text or "BAILOUT" in text:
            return self.get("POLICY_BACKSTOP")
        if "RATE" in text and ("CUT" in text or "LOWER" in text or "EASING" in text):
            return self.get("RATE_CUT")
        if "POLICY" in text or "CENTRAL_BANK" in text or "REGULATOR" in text:
            return self.get("POLICY_BACKSTOP")
        if "MARGIN" in text:
            return self.get("MARGIN_CALL")
        if "HAIRCUT" in text:
            return self.get("FUNDING_HAIRCUT")
        if "FUNDING" in text and (
            "PATH" in text
            or "RAIL" in text
            or "PLUMB" in text
            or "REPO" in text
            or "SOFR" in text
        ):
            return self.get("FUNDING_PATH_STRESS")
        if "REPO" in text and ("SPIKE" in text or "STRESS" in text):
            return self.get("FUNDING_PATH_STRESS")
        if "DEALER" in text or "CAPACITY_DROP" in text:
            return self.get("DEALER_CAPACITY_DROP")
        if "LIQUIDITY" in text and ("WITHDRAW" in text or "DRAIN" in text):
            return self.get("LIQUIDITY_WITHDRAWAL")
        if "DEPOSIT" in text and "RUN" in text:
            return self.get("DEPOSIT_RUN")
        if "FORCED_SELL" in text or "FIRE_SALE" in text:
            return self.get("FORCED_SELLING")
        if "DEFAULT" in text or "BANKRUPT" in text:
            return self.get("DEFAULT_EVENT")
        if "RUN" in text:
            return self.get("RUN_EVENT")
        if "MARKDOWN" in text or "MARK_DOWN" in text:
            return self.get("MARKDOWN_EVENT")
        if "COUNTERPARTY" in text:
            return self.get("COUNTERPARTY_FAILURE")
        if "RATING" in text or "DOWNGRADE" in text:
            return self.get("RATING_CASCADE")
        if "CORRELATION" in text:
            return self.get("CORRELATION_BREAK")
        if "VOL" in text or "VIX" in text:
            return self.get("VOL_SURFACE_KINK")
        if "TRANCHE" in text:
            return self.get("TRANCHE_REPRICING")
        if "BASIS" in text:
            return self.get("BASIS_DISLOCATION")
        if "SECURITIZATION" in text or "SECURITISATION" in text:
            return self.get("SECURITIZATION_STORAGE")
        if "OFF_BALANCE" in text:
            return self.get("OFF_BALANCE_SHEET_SHIFT")
        if "SYNTHETIC" in text:
            return self.get("SYNTHETIC_EXPOSURE_BUILDUP")
        if "COLLATERAL" in text and "TRANSFORMATION" in text:
            return self.get("COLLATERAL_TRANSFORMATION")
        return None


def build_default_operator_registry(enabled_families: list[str] | None = None) -> StructuralOperatorRegistry:
    enabled = set(enabled_families) if enabled_families else None
    return StructuralOperatorRegistry(
        operators={operator.name: operator for operator in default_structural_operators()},
        enabled_families=enabled,
    )


def default_structural_operators() -> list[StructuralOperator]:
    return [
        _op(
            "IDENTITY",
            "identity",
            {},
            aliases=("I", "NO_OP"),
            reversible=True,
            continuous=True,
            differentiable=True,
            state_dependent=False,
            path_dependent=False,
            description="Identity operator over structural state.",
        ),
        _op(
            "FUNDING_HAIRCUT",
            "compression",
            {"M": 0.18, "D": -0.22, "K": 0.10, "X": 0.12},
            aliases=("HAIRCUT", "FUNDING_HAIRCUT_OPERATOR", "COLLATERAL_HAIRCUT"),
            compressive=True,
            shadow_transfer=True,
            reflexive=True,
            sensitivity={"D_CONTRACTION": 0.55, "D_LOW": 0.25, "M": 0.15},
            description="Funding terms tighten, contracting feasible paths and pushing stress into shadow channels.",
        ),
        _op(
            "FUNDING_PATH_STRESS",
            "compression",
            {"M": 0.14, "D": -0.20, "K": 0.09, "X": 0.08},
            aliases=(
                "FUNDING_PATH",
                "FUNDING_RAIL_STRESS",
                "REPO_STRESS",
                "PLUMBING_STRESS",
                "SOFR_IORB_STRESS",
            ),
            compressive=True,
            reflexive=False,
            path_dependent=True,
            sensitivity={"D_CONTRACTION": 0.45, "M": 0.20, "X": 0.10},
            description=(
                "Overnight funding trades rich vs. the floor while reserves/TGA "
                "drain — the funding path itself is compressing before HY / "
                "equity vol confirm. Prototype operator (research-only) — see "
                "docs/operators/funding_path_stress.md."
            ),
        ),
        _op(
            "MARGIN_CALL",
            "compression",
            {"M": 0.16, "D": -0.25, "K": 0.16, "X": 0.07},
            aliases=("MARGIN", "COLLATERAL_CALL"),
            compressive=True,
            reflexive=True,
            sensitivity={"D_CONTRACTION": 0.45, "K": 0.25},
            description="Margin pressure forces deleveraging and amplifies path-order sensitivity.",
        ),
        _op(
            "LIQUIDITY_WITHDRAWAL",
            "compression",
            {"M": 0.12, "D": -0.20, "K": 0.08, "X": 0.05},
            aliases=("LIQUIDITY_DRAIN", "LIQUIDITY_WITHDRAW", "MARKET_LIQUIDITY_WITHDRAWAL"),
            compressive=True,
            sensitivity={"D_CONTRACTION": 0.35, "M": 0.15},
            description="Balance-sheet or market liquidity recedes, narrowing executable paths.",
        ),
        _op(
            "DEALER_CAPACITY_DROP",
            "compression",
            {"M": 0.10, "D": -0.18, "K": 0.13, "X": 0.08},
            aliases=("DEALER_BALANCE_SHEET_DROP", "DEALER_CAPACITY"),
            compressive=True,
            shadow_transfer=True,
            sensitivity={"D_CONTRACTION": 0.35, "X": 0.20},
            description="Intermediary balance-sheet capacity falls and market-making elasticity disappears.",
        ),
        _op(
            "DEPOSIT_RUN",
            "compression",
            {"M": 0.22, "D": -0.30, "K": 0.20, "X": 0.10},
            aliases=("BANK_RUN", "DEPOSIT_WITHDRAWAL_RUN"),
            compressive=True,
            reflexive=True,
            sensitivity={"D_CONTRACTION": 0.40, "SINGULAR_PRESSURE": 0.10},
            description="Depositor flight compresses funding degrees of freedom.",
        ),
        _op(
            "CORRELATION_BREAK",
            "curvature",
            {"M": 0.08, "D": -0.05, "K": 0.24, "X": 0.05},
            aliases=("CORRELATION_SPIKE", "CORRELATION_ONE"),
            sensitivity={"K": 0.35, "X": 0.10},
            description="Correlation assumptions fail and the transition map becomes more curved.",
        ),
        _op(
            "VOL_SURFACE_KINK",
            "curvature",
            {"M": 0.07, "D": -0.06, "K": 0.22, "X": 0.03},
            aliases=("VOL_KINK", "VIX_SPIKE", "VOL_SPIKE"),
            sensitivity={"K": 0.25, "M": 0.10},
            description="A volatility surface kink introduces local non-smoothness into state transitions.",
        ),
        _op(
            "TRANCHE_REPRICING",
            "curvature",
            {"M": 0.13, "D": -0.08, "K": 0.24, "X": 0.12},
            aliases=("TRANCHE_REPRICE", "STRUCTURED_CREDIT_REPRICING"),
            shadow_transfer=True,
            sensitivity={"X": 0.35, "K": 0.15},
            description="Structured-credit tranches reprice nonlinearly and expose hidden convexity.",
        ),
        _op(
            "BASIS_DISLOCATION",
            "curvature",
            {"M": 0.16, "D": -0.07, "K": 0.18, "X": 0.06},
            aliases=("BASIS_BLOWOUT", "BASIS_WIDENING"),
            sensitivity={"M": 0.25, "D_CONTRACTION": 0.20},
            description="Basis relationships detach and widen anchor mismatch.",
        ),
        _op(
            "RATING_CASCADE",
            "curvature",
            {"M": 0.15, "D": -0.12, "K": 0.20, "X": 0.10},
            aliases=("RATING_DOWNGRADE", "DOWNGRADE_CASCADE"),
            sensitivity={"D_CONTRACTION": 0.25, "X": 0.25},
            description="Discrete downgrades create a cascade of constraint and valuation kinks.",
        ),
        _op(
            "SECURITIZATION_STORAGE",
            "shadow_transfer",
            {"M": -0.03, "D": 0.03, "K": 0.04, "X": 0.18},
            aliases=("SECURITISATION_STORAGE", "SECURITIZATION", "RISK_STORAGE"),
            shadow_transfer=True,
            continuous=True,
            differentiable=True,
            sensitivity={"M": 0.10},
            description="Visible mismatch is partly stored in securitized or tranched shadow channels.",
        ),
        _op(
            "OFF_BALANCE_SHEET_SHIFT",
            "shadow_transfer",
            {"M": -0.02, "D": 0.01, "K": 0.05, "X": 0.20},
            aliases=("OFF_BALANCE", "OBS_SHIFT", "CONDUIT_SHIFT"),
            shadow_transfer=True,
            sensitivity={"M": 0.10, "K": 0.10},
            description="Pressure moves away from visible balance sheets into hidden commitments.",
        ),
        _op(
            "SYNTHETIC_EXPOSURE_BUILDUP",
            "shadow_transfer",
            {"M": 0.02, "D": -0.02, "K": 0.08, "X": 0.22},
            aliases=("SYNTHETIC_BUILDUP", "CDS_BUILDUP", "DERIVATIVE_EXPOSURE_BUILDUP"),
            shadow_transfer=True,
            continuous=True,
            sensitivity={"K": 0.15, "X": 0.15},
            description="Synthetic exposure accumulates latent realization pressure.",
        ),
        _op(
            "COLLATERAL_TRANSFORMATION",
            "shadow_transfer",
            {"M": -0.01, "D": -0.03, "K": 0.06, "X": 0.18},
            aliases=("COLLATERAL_REUSE", "COLLATERAL_TRANSFORM"),
            shadow_transfer=True,
            sensitivity={"D_CONTRACTION": 0.15, "X": 0.15},
            description="Collateral chains transform apparent liquidity into hidden fragility.",
        ),
        _op(
            "FORCED_SELLING",
            "realization",
            {"M": 0.28, "D": -0.32, "K": 0.28, "X": -0.10},
            aliases=("FIRE_SALE", "FORCED_SELL", "LIQUIDATION_CASCADE"),
            compressive=True,
            reflexive=True,
            sensitivity={"X": 0.45, "D_CONTRACTION": 0.35, "K": 0.20},
            description="Hidden pressure is realized through forced liquidation and feedback selling.",
        ),
        _op(
            "DEFAULT_EVENT",
            "realization",
            {"M": 0.35, "D": -0.30, "K": 0.32, "X": -0.08},
            aliases=("DEFAULT", "FAILURE", "BANKRUPTCY"),
            compressive=True,
            reflexive=True,
            sensitivity={"X": 0.25, "SINGULAR_PRESSURE": 0.10},
            description="A default event realizes latent pressure and damages structural state.",
        ),
        _op(
            "RUN_EVENT",
            "realization",
            {"M": 0.25, "D": -0.35, "K": 0.22, "X": -0.12},
            aliases=("RUN", "MARKET_RUN", "INVESTOR_RUN"),
            compressive=True,
            reflexive=True,
            sensitivity={"D_CONTRACTION": 0.30, "X": 0.25},
            description="A generalized run turns hidden pressure into visible withdrawal pressure.",
        ),
        _op(
            "MARKDOWN_EVENT",
            "realization",
            {"M": 0.24, "D": -0.18, "K": 0.22, "X": -0.08},
            aliases=("MARKDOWN", "MARK_DOWN", "WRITE_DOWN"),
            compressive=True,
            sensitivity={"X": 0.25, "K": 0.15},
            description="A valuation markdown realizes previously deferred losses.",
        ),
        _op(
            "COUNTERPARTY_FAILURE",
            "realization",
            {"M": 0.30, "D": -0.26, "K": 0.26, "X": -0.06},
            aliases=("COUNTERPARTY_DEFAULT", "COUNTERPARTY"),
            compressive=True,
            reflexive=True,
            sensitivity={"K": 0.20, "X": 0.25},
            description="Counterparty failure converts network opacity into visible state deformation.",
        ),
        _op(
            "POLICY_BACKSTOP",
            "intervention",
            {"M": -0.18, "D": 0.24, "K": -0.14, "X": -0.03},
            aliases=("BACKSTOP", "POLICY_SUPPORT", "BAILOUT", "EMERGENCY_SUPPORT"),
            recovery=True,
            sensitivity={"SINGULAR_PRESSURE": 0.08},
            description="Policy support widens feasible paths without undoing the prior event history.",
        ),
        _op(
            "RATE_CUT",
            "intervention",
            {"M": -0.06, "D": 0.08, "K": -0.02, "X": 0.02},
            aliases=("POLICY_RATE_CUT", "MONETARY_EASING"),
            recovery=True,
            continuous=True,
            differentiable=True,
            sensitivity={"M": 0.05},
            description="Rate easing reduces visible mismatch but can leave some deferred pressure.",
        ),
        _op(
            "QE",
            "intervention",
            {"M": -0.12, "D": 0.18, "K": -0.05, "X": 0.04},
            aliases=("QUANTITATIVE_EASING", "ASSET_PURCHASE"),
            recovery=True,
            continuous=True,
            sensitivity={"D_CONTRACTION": 0.15, "M": 0.10},
            description="Asset purchases expand liquidity capacity while transferring part of the structure.",
        ),
        _op(
            "LIQUIDITY_FACILITY",
            "intervention",
            {"M": -0.14, "D": 0.22, "K": -0.10, "X": 0.03},
            aliases=("LIQUIDITY_BACKSTOP", "LIQUIDITY_INJECTION", "FACILITY"),
            recovery=True,
            sensitivity={"D_CONTRACTION": 0.25, "M": 0.10},
            description="A targeted facility restores funding paths but does not erase historical damage.",
        ),
        _op(
            "DEPOSIT_GUARANTEE",
            "intervention",
            {"M": -0.18, "D": 0.25, "K": -0.08, "X": -0.04},
            aliases=("DEPOSIT_INSURANCE", "GUARANTEE"),
            recovery=True,
            sensitivity={"D_CONTRACTION": 0.20, "M": 0.15},
            description="Deposit guarantees arrest run dynamics by widening funding degrees of freedom.",
        ),
        _op(
            "COORDINATED_RESCUE",
            "intervention",
            {"M": -0.22, "D": 0.26, "K": -0.16, "X": 0.02},
            aliases=("COORDINATED_SUPPORT", "SYSTEM_RESCUE"),
            recovery=True,
            reflexive=True,
            sensitivity={"SINGULAR_PRESSURE": 0.08},
            description="Coordinated rescue lowers singular pressure by changing the state trajectory.",
        ),
    ]


def _op(name: str, family: str, delta: dict[str, float], **kwargs: Any) -> StructuralOperator:
    return StructuralOperator(name=name, family=family, delta=delta, **kwargs)


def _candidate_tokens(event: Mapping[str, Any]) -> list[str]:
    tokens: list[str] = []
    for key in ("operator", "operator_name", "event", "event_type", "intervention_type"):
        value = event.get(key)
        if value:
            tokens.append(str(value))
    return tokens


def _event_text(event: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "operator",
        "operator_name",
        "event",
        "event_type",
        "intervention_type",
        "channel",
        "actor",
        "expected_direction",
        "affected_proxy",
        "description",
    ):
        value = event.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts)


def _normalize(value: str) -> str:
    text = str(value).strip().upper()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")
