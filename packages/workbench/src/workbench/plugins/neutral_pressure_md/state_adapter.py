"""Neutral-pressure adapter from ModelResult to generic DecisionEvidence."""
from __future__ import annotations

from workbench.model_protocol import DecisionEvidence, ModelResult, PROTOCOL_VERSION


class NeutralPressureStateAdapter:
    """Map the generic score vector into the existing neutral-state contract."""

    adapter_id = "neutral_pressure_state"
    adapter_version = "1.0.0"
    approved = True

    def adapt(self, result: ModelResult) -> DecisionEvidence:
        result.validate()
        return DecisionEvidence(
            protocol_version=PROTOCOL_VERSION,
            model_id=result.model_id,
            model_version=result.model_version,
            state=result.state,
            scores=dict(result.scores),
            confidence=result.confidence,
            diagnostics={
                "model_status": result.status,
                "model_diagnostics": dict(result.diagnostics),
                "adapter_role": "neutral_state",
            },
            provenance={
                **dict(result.provenance),
                "input_digest": result.input_digest,
                "implementation_digest": result.implementation_digest,
            },
            authority="DIAGNOSTIC_ONLY",
            claim_ceiling=result.claim_ceiling,
            research_only=False,
            diagnostic_only=True,
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
        )


__all__ = ["NeutralPressureStateAdapter"]
