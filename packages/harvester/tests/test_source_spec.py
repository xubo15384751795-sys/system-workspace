from __future__ import annotations

from pathlib import Path

import pytest

from harvester.core.source_spec import (
    SourceRegistryValidationError,
    load_source_registry,
    validate_source_registry,
)


ROOT = Path(__file__).resolve().parents[3]


def test_workspace_source_registry_is_typed_and_semantic() -> None:
    registry = load_source_registry(ROOT / "configs" / "source_registry.yaml")

    assert registry.schema_version == "system.source_registry.v1"
    assert registry.authority_id("ecb") == "ecb"
    etf = registry.get("ETF_EOD_ADJUSTED")
    assert etf is not None
    assert etf.primary_key == ("symbol", "date")
    assert [route.source_id for route in etf.routes] == ["tiingo", "massive", "yfinance"]
    assert etf.route_for("yfinance").diagnostic_only is True  # type: ignore[union-attr]
    assert len(etf.authoritative_routes) == 2
    assert registry.authority_id("cboe") == "cboe"
    assert registry.get("SOFR").route_for("fred").fallback_kind == "primary"  # type: ignore[union-attr]
    assert registry.get("FRED_SERIES").route_for("fred").transport == "owned_http_gateway"  # type: ignore[union-attr]


def test_source_registry_rejects_unknown_route_source() -> None:
    payload = {
        "schema_version": "system.source_registry.v1",
        "sources": {
            "tiingo": {
                "authority_id": "tiingo",
                "authority_class": "market",
                "official_url": "https://example.test/tiingo",
            }
        },
        "series": {
            "TEST": {
                "dataset_id": "test",
                "semantic_equivalence_group": "test",
                "frequency": "daily",
                "adjustment_policy": "none",
                "primary_key": ["date"],
                "routes": [
                    {
                        "route_id": "bad_route",
                        "source_id": "missing",
                        "tier": 1,
                        "transport": "fixture",
                        "fallback_kind": "primary",
                        "claim_ceiling": "observed_source",
                        "diagnostic_only": False,
                    }
                ],
            }
        },
    }

    with pytest.raises(SourceRegistryValidationError, match="unknown source"):
        validate_source_registry(payload)
