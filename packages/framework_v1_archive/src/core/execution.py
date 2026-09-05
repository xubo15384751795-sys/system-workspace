from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.core.models import _freeze_mapping, NarrativeReading
from src.operators.operator_schema import OperatorDiagnostics


@dataclass(frozen=True)
class RunContext:
    run_date: str
    run_type: str
    history_start: str
    series_ids: tuple[str, ...]
    config: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_ids", tuple(str(item) for item in self.series_ids))
        object.__setattr__(self, "config", _freeze_mapping(self.config))

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        run_date: str | None = None,
        run_type: str | None = None,
    ) -> RunContext:
        return cls(
            run_date=str(run_date or config["default_run_date"]),
            run_type=str(run_type or config["default_run_type"]),
            history_start=str(config["history_start"]),
            series_ids=tuple(str(item) for item in config.get("series_ids", ())),
            config=config,
        )


@dataclass(frozen=True)
class DiagnosticBundle:
    z_vector: Any
    sigma_t: float | None
    singular_flag: bool | None
    anomaly_score: float | None
    reflexivity_flags: Mapping[str, bool]
    operator_diagnostics: OperatorDiagnostics | None
    narrative: NarrativeReading | None
    leading_channel: str | None = None
    pattern: str | None = None
    escalation: bool = False
    escalation_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "reflexivity_flags", _freeze_mapping(self.reflexivity_flags))
