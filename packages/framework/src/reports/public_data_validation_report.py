from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class PublicDataValidationReport:
    executive_verdict: str
    fair_public_data_benchmark_results: pd.DataFrame = field(default_factory=pd.DataFrame)
    vulnerability_vs_transition_results: pd.DataFrame = field(default_factory=pd.DataFrame)
    oos_validation_results: pd.DataFrame = field(default_factory=pd.DataFrame)
    ablation_results: pd.DataFrame = field(default_factory=pd.DataFrame)
    threshold_perturbation_results: pd.DataFrame = field(default_factory=pd.DataFrame)
    baseline_rank: int | None = None
    allowed_claims: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    next_repair_steps: tuple[str, ...] = (
        "Complete public benchmark coverage.",
        "Run rolling-origin OOS validation before early-warning language.",
    )

    def to_markdown(self) -> str:
        lines = [
            "# Public Data Validation Report",
            "## Executive verdict",
            self.executive_verdict,
            "## Fair public-data benchmark results",
            _frame(self.fair_public_data_benchmark_results),
            "## Vulnerability vs transition results",
            _frame(self.vulnerability_vs_transition_results),
            "## OOS validation results",
            _frame(self.oos_validation_results),
            "## Ablation results",
            _frame(self.ablation_results),
            "## Threshold perturbation results",
            _frame(self.threshold_perturbation_results),
            "## Baseline rank",
            str(self.baseline_rank) if self.baseline_rank is not None else "Not established.",
            "## Allowed claims",
            "\n".join(f"- {claim}" for claim in self.allowed_claims) or "- Forensic public-data explanation only.",
            "## Forbidden claims",
            "\n".join(f"- {claim}" for claim in self.forbidden_claims) or "- Portfolio and validated early-warning claims.",
            "## Next repair steps",
            "\n".join(f"- {step}" for step in self.next_repair_steps),
        ]
        return "\n\n".join(lines)


def build_public_data_validation_report(**kwargs) -> PublicDataValidationReport:
    return PublicDataValidationReport(
        executive_verdict=kwargs.pop(
            "executive_verdict",
            "The project remains a public-data structural risk dashboard, not a proven hedge-fund alpha model.",
        ),
        **kwargs,
    )


def _frame(frame: pd.DataFrame) -> str:
    if frame is None or frame.empty:
        return "Not run or insufficient public data."
    return frame.to_markdown(index=False)
