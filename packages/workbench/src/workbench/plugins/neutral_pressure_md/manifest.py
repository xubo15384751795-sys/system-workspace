"""Manifest for the frozen neutral-pressure M/D model."""
from __future__ import annotations

import hashlib
from pathlib import Path

from workbench.model_protocol import ModelManifest, PROTOCOL_VERSION


def manifest_for(implementation_path: Path) -> ModelManifest:
    digest = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
    return ModelManifest(
        model_id="neutral_pressure_md",
        model_version="1.0.0",
        protocol_version=PROTOCOL_VERSION,
        input_contract={
            "type": "admitted_benchmark_panel",
            "required_columns": ["date", "series_id", "value"],
            "input_ref": "explicit_capability_reference",
        },
        output_contract={
            "type": "generic_model_result",
            "private_payload": "opaque_to_consumers",
            "scores_nullable": True,
        },
        required_data=(
            "DERIVED:CP_TBILL_SPREAD",
            "DERIVED:SOFR_IORB_SPREAD",
            "FRED:NFCICREDIT",
            "FRED:NFCIRISK",
            "CBOE:MOVE",
            "DERIVED:SPX_ROLL_SPREAD",
        ),
        required_capabilities=("data_access",),
        failure_semantics=(
            "return degraded result when one or more gauges are unavailable; "
            "raise on unusable input"
        ),
        determinism_policy="deterministic_given_input_panel_and_request_metadata",
        reference="docs/measurements/macro_pressure_mechanism_cards.md",
        implementation_digest=digest,
        fixture_version="neutral_pressure_md.fixture.v1",
    )


__all__ = ["manifest_for"]
