"""Observation integrity diagnostics (OBS-1 / OBS-2): provider checks and case-level summary."""

from __future__ import annotations

from dataclasses import dataclass

_CHECK_STATUS = frozenset({"pass", "watch", "warn", "fail", "unknown"})
_OVERALL_STATUS = frozenset({"strong", "medium", "weak", "failed", "unknown"})


def _validate_ratio(name: str, value: float | None) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be None or in [0, 1]; got {value!r}")


def _validate_non_negative(name: str, value: float | None) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or value < 0.0:
        raise ValueError(f"{name} must be None or non-negative; got {value!r}")


@dataclass(frozen=True)
class ProviderIntegrityCheck:
    logical_series: str
    provider: str | None
    status: str
    frequency: str | None
    required_resolution: str | None
    missingness_ratio: float | None
    forward_fill_ratio: float | None
    event_window_variance: float | None
    staleness_score: float | None
    provider_disagreement: float | None
    fallback_used: bool
    mock_used: bool
    issues: list[str]
    interpretation: str

    def __post_init__(self) -> None:
        if self.status not in _CHECK_STATUS:
            raise ValueError(f"status must be one of {sorted(_CHECK_STATUS)}; got {self.status!r}")
        object.__setattr__(self, "issues", list(self.issues))
        _validate_ratio("missingness_ratio", self.missingness_ratio)
        _validate_ratio("forward_fill_ratio", self.forward_fill_ratio)
        _validate_ratio("provider_disagreement", self.provider_disagreement)
        _validate_non_negative("event_window_variance", self.event_window_variance)
        _validate_non_negative("staleness_score", self.staleness_score)

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "logical_series": self.logical_series,
            "provider": self.provider,
            "status": self.status,
            "frequency": self.frequency,
            "required_resolution": self.required_resolution,
            "missingness_ratio": self.missingness_ratio,
            "forward_fill_ratio": self.forward_fill_ratio,
            "event_window_variance": self.event_window_variance,
            "staleness_score": self.staleness_score,
            "provider_disagreement": self.provider_disagreement,
            "fallback_used": self.fallback_used,
            "mock_used": self.mock_used,
            "issues": list(self.issues),
            "interpretation": self.interpretation,
        }


@dataclass(frozen=True)
class ObservationIntegrity:
    case_id: str | None
    overall_status: str
    checks: list[ProviderIntegrityCheck]
    static_source_risk: float | None
    provider_disagreement_available: bool
    summary: str
    diagnostic_only: bool = True

    def __post_init__(self) -> None:
        if self.overall_status not in _OVERALL_STATUS:
            raise ValueError(
                f"overall_status must be one of {sorted(_OVERALL_STATUS)}; got {self.overall_status!r}"
            )
        if self.diagnostic_only is not True:
            raise ValueError("diagnostic_only must remain True for observation integrity diagnostics")
        object.__setattr__(self, "checks", list(self.checks))
        _validate_non_negative("static_source_risk", self.static_source_risk)

    def to_serializable_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "overall_status": self.overall_status,
            "checks": [c.to_serializable_dict() for c in self.checks],
            "static_source_risk": self.static_source_risk,
            "provider_disagreement_available": self.provider_disagreement_available,
            "summary": self.summary,
            "diagnostic_only": self.diagnostic_only,
        }
