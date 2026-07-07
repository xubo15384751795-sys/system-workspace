"""Mismatch diagnostic models and morphology label adapter (diagnostic-only; not scoring)."""

from __future__ import annotations

from dataclasses import dataclass, field

_MISMATCH_STATUS = frozenset({"normal", "watch", "warning", "critical", "unknown"})


def _validate_pair(pair: tuple[str, str]) -> None:
    if len(pair) != 2:
        raise ValueError("pair must contain exactly two strings")
    a, b = pair
    if not isinstance(a, str) or not isinstance(b, str) or not a.strip() or not b.strip():
        raise ValueError("pair entries must be non-empty strings")


@dataclass(frozen=True)
class MismatchProfile:
    pair: tuple[str, str]
    mismatch_type: str
    status: str
    magnitude: float | None
    direction: str | None
    persistence: float | None
    evidence: list[str]
    implication: str

    def __post_init__(self) -> None:
        _validate_pair(self.pair)
        if self.status not in _MISMATCH_STATUS:
            raise ValueError(
                f"status must be one of {sorted(_MISMATCH_STATUS)}; got {self.status!r}"
            )
        if self.magnitude is not None and self.magnitude < 0:
            raise ValueError("magnitude must be None or non-negative")
        if self.persistence is not None and not (0.0 <= self.persistence <= 1.0):
            raise ValueError("persistence must be None or in [0, 1]")

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "pair": list(self.pair),
            "mismatch_type": self.mismatch_type,
            "status": self.status,
            "magnitude": self.magnitude,
            "direction": self.direction,
            "persistence": self.persistence,
            "evidence": list(self.evidence),
            "implication": self.implication,
        }


@dataclass(frozen=True)
class MismatchMap:
    case_id: str | None
    profiles: list[MismatchProfile]
    summary: str
    source: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "profiles", list(self.profiles))

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "profiles": [p.to_serializable_dict() for p in self.profiles],
            "summary": self.summary,
            "source": self.source,
        }


def map_morphology_to_mismatch(morphology_label: str, case_id: str | None = None) -> MismatchMap:
    """Map a morphology classifier label to a diagnostic MismatchMap (label semantics only; no classifier I/O)."""
    label = morphology_label.strip()
    source = "morphology_label_adapter"

    if label == "anchor_mismatch_plus_path_contraction":
        profile = MismatchProfile(
            pair=("A", "L"),
            mismatch_type="anchor_path_mismatch",
            status="warning",
            magnitude=None,
            direction=None,
            persistence=None,
            evidence=[f"morphology_label={label}"],
            implication="Anchor remains legible while liquidation path feasibility is contracting.",
        )
        return MismatchMap(
            case_id=case_id,
            profiles=[profile],
            summary="Mapped anchor–liquidation path morphology to anchor/path mismatch diagnostic.",
            source=source,
        )

    if label == "transition_deformation_with_path_collapse":
        profile = MismatchProfile(
            pair=("K", "D"),
            mismatch_type="transition_path_mismatch",
            status="warning",
            magnitude=None,
            direction=None,
            persistence=None,
            evidence=[f"morphology_label={label}"],
            implication="Transition deformation is coupled with path collapse pressure.",
        )
        return MismatchMap(
            case_id=case_id,
            profiles=[profile],
            summary="Mapped transition/path-collapse morphology to transition/path mismatch diagnostic.",
            source=source,
        )

    if label == "shadow_stock_with_transition_deformation":
        profile = MismatchProfile(
            pair=("X", "K"),
            mismatch_type="shadow_transition_mismatch",
            status="warning",
            magnitude=None,
            direction=None,
            persistence=None,
            evidence=[f"morphology_label={label}"],
            implication="Accumulated shadow stock is interacting with transition deformation.",
        )
        return MismatchMap(
            case_id=case_id,
            profiles=[profile],
            summary="Mapped shadow/transition morphology to shadow–transition mismatch diagnostic.",
            source=source,
        )

    return MismatchMap(
        case_id=case_id,
        profiles=[],
        summary=f"No mismatch mapping is defined for morphology label {label!r}.",
        source=source,
    )


_PROFILE_TYPES = frozenset(
    {"accounting_market", "deposit_liquidity", "model_market", "p_tau", "provider_reality"}
)


def build_mismatch_profile_by_type(
    mismatch_type: str,
    *,
    status: str = "warning",
    magnitude: float | None = None,
    direction: str | None = None,
    persistence: float | None = None,
    evidence: list[str] | None = None,
    implication: str | None = None,
    pair: tuple[str, str] | None = None,
) -> MismatchProfile:
    """Construct a typed mismatch profile for curated case diagnostics (does not replace morphology adapter)."""
    key = mismatch_type.strip()
    if key not in _PROFILE_TYPES:
        raise ValueError(f"Unknown mismatch_type {key!r}; expected one of {sorted(_PROFILE_TYPES)}")

    default_pair: tuple[str, str]
    default_implication: str
    default_evidence: list[str]

    if key == "accounting_market":
        default_pair = ("A", "V")
        default_implication = (
            "Hold-to-maturity anchoring diverges from mark-to-market paths that govern loss absorption "
            "when funding stress forces recognition."
        )
        default_evidence = ["mismatch_type=accounting_market"]
    elif key == "deposit_liquidity":
        default_pair = ("L", "A")
        default_implication = (
            "Deposit outflow intensity is misaligned with the speed and depth at which assets can be "
            "monetized without breaking anchor assumptions."
        )
        default_evidence = ["mismatch_type=deposit_liquidity"]
    elif key == "model_market":
        default_pair = ("K", "D")
        default_implication = (
            "Model-implied convergence and liquidity paths underestimate realized slippage when "
            "financing and collateral rules tighten simultaneously."
        )
        default_evidence = ["mismatch_type=model_market"]
    elif key == "p_tau":
        default_pair = ("P", "τ")
        default_implication = (
            "Policy reaction latency exceeds the market's clearing speed, producing a temporary regime "
            "where prices move faster than rules can be rewritten."
        )
        default_evidence = ["mismatch_type=p_tau"]
    else:  # provider_reality
        default_pair = ("S", "τ")
        default_implication = (
            "Published series and observation windows lag the event clock, overstating continuity during "
            "discontinuous repricing."
        )
        default_evidence = ["mismatch_type=provider_reality"]

    use_pair = pair if pair is not None else default_pair
    use_implication = implication if implication is not None else default_implication
    use_evidence = list(evidence) if evidence is not None else list(default_evidence)

    return MismatchProfile(
        pair=use_pair,
        mismatch_type=key,
        status=status,
        magnitude=magnitude,
        direction=direction,
        persistence=persistence,
        evidence=use_evidence,
        implication=use_implication,
    )
