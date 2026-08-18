from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from harvester.core.proxy_measurement import (
    PROXY_CLAIM_CEILING,
    build_proxy_measurement_spec,
    load_measurement_spec,
    validate_measurement_spec,
)
from harvester.registry import RegistrySeries, SeriesRegistry


def _registry() -> SeriesRegistry:
    return SeriesRegistry(
        schema_version="1.0",
        series={
            "VIXCLS": RegistrySeries(
                canonical_id="VIXCLS",
                source_series_id="VIXCLS",
                provider_priority=("fred", "openbb_fred"),
                measurement_block="volatility",
                structural_role="spot_volatility",
                frequency="daily",
            ),
            "MOVE_PROXY": RegistrySeries(
                canonical_id="MOVE_PROXY",
                source_series_id="MOVE_PROXY",
                provider_priority=("derived",),
                measurement_block="rates_volatility",
                structural_role="rates_volatility_synthetic_proxy",
                frequency="daily",
                quality_expectation="synthetic",
                derived=True,
                synthetic_proxy=True,
                formula="VIXCLS * 0.5",
                inputs=("VIXCLS",),
            ),
        },
        providers={},
    )


def test_proxy_spec_is_explicitly_non_promotable() -> None:
    registry = _registry()
    panel = pd.DataFrame(
        {
            "source_series_id": ["MOVE_PROXY", "MOVE_PROXY"],
            "value": [10.0, 11.0],
        }
    )

    spec = build_proxy_measurement_spec(
        release_id="2026-08-17-r1",
        derived_series=[registry.get("MOVE_PROXY")],
        registry=registry,
        candidate_panel=panel,
        captured_at="2026-08-17T00:00:00Z",
    )

    validate_measurement_spec(spec)
    assert spec["derivation"] == "PROXY_DERIVED"
    assert spec["claim_ceiling"] == PROXY_CLAIM_CEILING
    assert spec["promotion_allowed"] is False
    assert spec["missingness_policy"]["imputation_allowed"] is False
    assert spec["missingness_policy"]["carry_forward_allowed"] is False
    assert "canonical_chain_path" not in spec
    assert spec["candidate_series"][0]["source_ladder"] == [
        {
            "tier": 1,
            "input_series_ids": ["VIXCLS"],
            "source_ids": ["fred"],
            "role": "PRIMARY",
        },
        {
            "tier": 2,
            "input_series_ids": ["VIXCLS"],
            "source_ids": ["openbb_fred"],
            "role": "FALLBACK",
        },
    ]


def test_proxy_spec_round_trips_and_rejects_authority_fields(tmp_path: Path) -> None:
    registry = _registry()
    spec = build_proxy_measurement_spec(
        release_id="2026-08-17-r1",
        derived_series=[registry.get("MOVE_PROXY")],
        registry=registry,
        candidate_panel=pd.DataFrame(columns=["source_series_id"]),
        captured_at="2026-08-17T00:00:00Z",
    )
    path = tmp_path / "proxy_candidate_panel.measurement_spec.json"
    path.write_text(json.dumps(spec) + "\n", encoding="utf-8")
    assert load_measurement_spec(path)["candidate_row_count"] == 0

    invalid = dict(spec)
    invalid["promotion_allowed"] = True
    try:
        validate_measurement_spec(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("proxy measurement spec must reject promotion authority")
