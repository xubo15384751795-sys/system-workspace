"""Tests for cross-asset panel Harvester dataset staging."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
from harvester.cross_asset_panel import (
    PANEL_COLUMNS,
    build_cross_asset_panel,
    compute_derived_columns,
    prefetched_panel_from_registry,
    stage_cross_asset_panel,
    sync_panel_to_workspace,
)


def test_compute_derived_columns_adds_returns(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "symbol": ["SPY", "SPY", "SPY"],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.0, 102.0, 101.0],
            "volume": [1_000, 1_100, 1_200],
        }
    )
    derived = compute_derived_columns(frame)
    assert "return_1d" in derived.columns
    assert derived.loc[1, "return_1d"] == pytest.approx(0.02)


def test_compute_derived_columns_deduplicates_symbol_date() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"]),
            "symbol": ["TLT", "TLT", "TLT"],
            "open": [100.0, 100.000001, 101.0],
            "high": [101.0, 101.000001, 102.0],
            "low": [99.0, 99.000001, 100.0],
            "close": [100.0, 100.000001, 101.0],
            "volume": [1_000, 1_001, 1_100],
        }
    )

    derived = compute_derived_columns(frame)

    assert len(derived) == 2
    assert not derived.duplicated(["symbol", "date"]).any()
    assert derived.iloc[0]["close"] == pytest.approx(100.000001)
    assert derived.iloc[1]["return_1d"] == pytest.approx(0.00999999, rel=1e-6)


def test_stage_cross_asset_panel_writes_manifest_and_workspace_copy(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-16", "2026-06-17"]),
            "symbol": ["SPY", "SPY"],
            "open": [500.0, 501.0],
            "high": [502.0, 503.0],
            "low": [499.0, 500.0],
            "close": [501.0, 502.0],
            "volume": [1.0, 1.0],
            "return_1d": [0.0, 0.002],
            "return_5d": [0.0, 0.0],
            "return_20d": [0.0, 0.0],
            "return_60d": [0.0, 0.0],
            "volatility_20d": [0.0, 0.0],
            "drawdown_60d": [0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def fake_fetch(symbols, *, period="5d"):
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-18"]),
                "symbol": ["SPY"],
                "open": [503.0],
                "high": [504.0],
                "low": [502.0],
                "close": [503.5],
                "volume": [2.0],
            }
        )

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", fake_fetch)
    monkeypatch.setattr("harvester.cross_asset_panel.resolve_etf_universe", lambda workspace=None: ["SPY"])
    monkeypatch.chdir(workspace)

    release_dir = tmp_path / "release"
    info = stage_cross_asset_panel(
        release_dir,
        release_id="2026-06-18-r1",
        as_of_date="2026-06-20",
        vintage_date="2026-06-20",
        workspace=workspace,
    )

    assert info["row_count"] == 3
    assert (release_dir / "data" / "cross_asset_daily_panel.parquet").exists()
    assert (release_dir / "manifests" / "cross_asset_daily_panel.manifest.json").exists()
    assert (release_dir / "provenance" / "cross_asset_daily_panel.provenance.json").exists()
    canonical_path = release_dir / "provenance" / "cross_asset_daily_panel.canonical_observations.jsonl"
    assert canonical_path.exists()
    canonical_records = [
        json.loads(line)
        for line in canonical_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(canonical_records) == 3
    assert canonical_records[0]["observation_id"].startswith("obs_")
    from system_runtime.canonical_ids import validate_observation
    from system_runtime.canonical_ids import validate_chain

    for record in canonical_records:
        validate_observation(record)
    canonical_chain_path = release_dir / "provenance" / "cross_asset_daily_panel.canonical_chains.jsonl"
    canonical_chains = [
        json.loads(line)
        for line in canonical_chain_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(canonical_chains) == 3
    for chain in canonical_chains:
        validate_chain(chain)
        assert chain["claim"]["status"] == "WATCH"
        assert chain["claim"]["provenance"]["claim_ceiling"] == "diagnostic_observation_only"
        assert chain["claim"]["provenance"]["promotion_allowed"] is False
    assert (release_dir / "quality_reports" / "cross_asset_daily_panel.quality.json").exists()
    manifest = pd.read_json(
        release_dir / "manifests" / "cross_asset_daily_panel.manifest.json",
        typ="series",
    )
    assert manifest["time_coverage"]["end"] == "2026-06-18"
    assert manifest["provider_outcome"]["status"] == "refreshed"
    provenance = json.loads(
        (release_dir / "provenance" / "cross_asset_daily_panel.provenance.json").read_text(
            encoding="utf-8"
        )
    )
    assert provenance["canonical_observation_count"] == 3
    assert provenance["canonical_chain_count"] == 3
    assert provenance["canonical_chain_path"].endswith(".canonical_chains.jsonl")
    assert provenance["canonical_schema_version"] == "system.canonical_chain.v2"
    assert provenance["canonical_lineage_path"].endswith(".canonical_lineage.v2.json")
    workspace_copy = workspace / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    assert workspace_copy.exists()
    copied = pd.read_parquet(workspace_copy)
    assert list(copied.columns) == PANEL_COLUMNS
    assert len(copied) == 3


def test_shadow_contract_records_block_without_replacing_workspace_mirror(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    mirror = workspace / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    mirror.parent.mkdir(parents=True)
    valid = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-17"]),
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [2.0],
            "return_1d": [0.0],
            "return_5d": [0.0],
            "return_20d": [0.0],
            "return_60d": [0.0],
            "volatility_20d": [0.0],
            "drawdown_60d": [0.0],
        }
    )
    valid.to_parquet(mirror, index=False)
    before = mirror.read_bytes()
    invalid = pd.concat([valid, valid], ignore_index=True)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.build_cross_asset_panel",
        lambda **_kwargs: (
            invalid,
            {
                "status": "refreshed",
                "provider": "fixture",
                "requested_count": 1,
                "succeeded_count": 1,
                "failed_count": 0,
                "failed_series": [],
                "retrieved_at": "2026-06-18T00:00:00Z",
            },
        ),
    )
    monkeypatch.setattr("harvester.cross_asset_panel.resolve_etf_universe", lambda workspace=None: ["SPY"])

    info = stage_cross_asset_panel(
        tmp_path / "release",
        release_id="2026-06-18-r2",
        as_of_date="2026-06-18",
        vintage_date="2026-06-18",
        workspace=workspace,
        data_contract_mode="shadow",
    )

    assert info["provider_outcome"]["data_contract"]["status"] == "BLOCK"
    assert info["provider_outcome"]["data_contract"]["mode"] == "shadow"
    assert mirror.read_bytes() == before


def test_build_cross_asset_panel_returns_columns_when_seeded(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-17"]),
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [1.0],
            "return_1d": [0.0],
            "return_5d": [0.0],
            "return_20d": [0.0],
            "return_60d": [0.0],
            "volatility_20d": [0.0],
            "drawdown_60d": [0.0],
        }
    ).to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", lambda symbols, period="5d": pd.DataFrame())
    monkeypatch.setattr("harvester.cross_asset_panel.resolve_etf_universe", lambda workspace=None: ["SPY"])

    panel = build_cross_asset_panel(workspace=workspace)
    assert not panel.empty
    assert set(PANEL_COLUMNS).issubset(panel.columns)


def test_registry_prefetch_is_consumed_before_fresh_provider_request(
    tmp_path: Path, monkeypatch
) -> None:
    """A release must not request registry-acquired ETF symbols twice."""
    workspace = tmp_path / "workspace"
    (workspace / "Data" / "panels").mkdir(parents=True)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["HYG", "SPY"],
    )
    calls: list[list[str]] = []

    def fake_fetch(symbols, *, period="5d"):
        calls.append(list(symbols))
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-08-12"]),
                "symbol": ["SPY"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1.0],
            }
        )

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", fake_fetch)
    prefetched = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-12"]),
            "symbol": ["HYG"],
            "open": [80.0],
            "high": [81.0],
            "low": [79.0],
            "close": [80.5],
            "volume": [1.0],
        }
    )

    panel, outcome = build_cross_asset_panel(
        workspace=workspace,
        prefetched_panel=prefetched,
        return_outcome=True,
    )

    assert calls == [["SPY"]]
    assert set(panel["symbol"]) == {"HYG", "SPY"}
    assert outcome["prefetched_series"] == ["HYG"]
    assert outcome["requested_count"] == 2
    assert outcome["succeeded_count"] == 2


def test_registry_rows_are_adapted_to_cross_asset_prefetch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["HYG", "SPY"],
    )
    registry_panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-12", "2026-08-12"]),
            "source_series_id": ["HYG", "NFCI"],
            "value": [80.5, 1.2],
            "open": [80.0, 1.2],
            "high": [81.0, 1.2],
            "low": [79.0, 1.2],
            "volume": [1.0, 0.0],
        }
    )

    prefetched = prefetched_panel_from_registry(registry_panel, workspace=tmp_path)

    assert list(prefetched["symbol"]) == ["HYG"]
    assert prefetched.iloc[0]["close"] == pytest.approx(80.5)


def test_registry_prefetch_filters_mixed_provider_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["HYG"],
    )
    registry_panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-12", "2026-08-12"]),
            "source_series_id": ["HYG", "NFCI"],
            "value": [80.5, 1.2],
            "open": [80.0, 1.2],
            "high": [81.0, 1.2],
            "low": [79.0, 1.2],
            "volume": [1.0, 0.0],
        }
    )
    registry_panel.attrs["provider_outcome"] = {
        "series_providers": {"HYG": "tiingo", "NFCI": "fred"},
        "series_attempts": {"HYG": [{"provider": "tiingo"}], "NFCI": [{"provider": "fred"}]},
        "series_source_signatures": {"HYG": {"source": "tiingo"}, "NFCI": {"source": "fred"}},
        "providers_used": ["tiingo", "fred"],
        "route_policy": {"diagnostic_only": True},
    }

    prefetched = prefetched_panel_from_registry(registry_panel, workspace=tmp_path)
    outcome = prefetched.attrs["provider_outcome"]

    assert outcome["series_providers"] == {"HYG": "tiingo"}
    assert outcome["series_attempts"] == {"HYG": [{"provider": "tiingo"}]}
    assert outcome["series_source_signatures"] == {"HYG": {"source": "tiingo"}}
    assert outcome["providers_used"] == ["tiingo"]
    assert "route_policy" not in outcome


def test_sync_panel_never_mutates_finalized_canonical_release(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    canonical = (
        workspace
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "data"
        / "cross_asset_daily_panel.parquet"
    )
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"finalized-release-bytes")
    before = canonical.read_bytes()

    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-12"]),
            "symbol": ["SPY"],
            "open": [99.0],
            "high": [101.0],
            "low": [98.0],
            "close": [100.0],
            "volume": [1_000.0],
        }
    )
    mirror = sync_panel_to_workspace(panel, workspace)

    assert mirror == workspace / "Data" / "panels" / "cross_asset_daily_panel.parquet"
    assert mirror.exists()
    assert canonical.read_bytes() == before


def test_sync_panel_blocks_invalid_candidate_and_preserves_existing_mirror(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    valid = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-08-11"]),
            "symbol": ["SPY"],
            "open": [99.0],
            "high": [101.0],
            "low": [98.0],
            "close": [100.0],
            "volume": [1_000.0],
        }
    )
    mirror = panel_dir / "cross_asset_daily_panel.parquet"
    valid.to_parquet(mirror, index=False)
    before = mirror.read_bytes()

    invalid = valid.drop(columns=["volume"])
    with pytest.raises(ValueError, match="DATA_CONTRACT_VIOLATION"):
        sync_panel_to_workspace(invalid, workspace)

    assert mirror.read_bytes() == before


def test_fetch_recent_ohlcv_accepts_provider_value_column(monkeypatch) -> None:
    """EtfYfinanceProvider emits Close as 'value'; must not be dropped as close=0."""
    from harvester.cross_asset_panel import fetch_recent_ohlcv
    from harvester.providers.base import ProviderResult

    # The production chain prefers authenticated providers.  This fixture is
    # specifically exercising the yfinance adapter, so make that dependency
    # explicit instead of allowing the test to call a real upstream service.
    monkeypatch.setenv("ETF_PROVIDER_CHAIN", "yfinance")

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_series(self, series_ids):
            frame = pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-07-10"]),
                    "value": [754.95],
                    "open": [752.0],
                    "high": [755.0],
                    "low": [751.0],
                    "volume": [1.0],
                }
            )
            return [
                ProviderResult(
                    provider="yfinance",
                    series_id="SPY",
                    frame=frame,
                )
            ]

    monkeypatch.setattr(
        "harvester.providers.etf_yfinance.EtfYfinanceProvider",
        FakeProvider,
    )
    fresh = fetch_recent_ohlcv(["SPY"], period="5d")
    assert len(fresh) == 1
    assert fresh.iloc[0]["close"] == pytest.approx(754.95)
    assert fresh.iloc[0]["symbol"] == "SPY"


def test_fetch_recent_ohlcv_raises_when_all_symbols_fail(monkeypatch) -> None:
    from harvester.cross_asset_panel import fetch_recent_ohlcv
    from harvester.providers.base import ProviderResult

    # Keep this failure-path fixture deterministic; the default chain may use
    # Tiingo/Massive before yfinance when credentials are present.
    monkeypatch.setenv("ETF_PROVIDER_CHAIN", "yfinance")

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_series(self, series_ids):
            return [
                ProviderResult(
                    provider="yfinance",
                    series_id="SPY",
                    frame=pd.DataFrame(),
                    fetch_error="rate limited",
                )
            ]

    monkeypatch.setattr(
        "harvester.providers.etf_yfinance.EtfYfinanceProvider",
        FakeProvider,
    )
    with pytest.raises(RuntimeError, match="no usable rows") as exc_info:
        fetch_recent_ohlcv(["SPY"], period="5d")
    assert exc_info.value.outcome["status"] == "provider_failed_no_acceptable_fallback"


def test_full_33_symbol_provider_failure_never_reports_refreshed(monkeypatch) -> None:
    from harvester.cross_asset_panel import fetch_recent_ohlcv
    from harvester.providers.base import ProviderResult

    # Exercise the yfinance failure fixture directly; do not let credentials
    # in a developer environment short-circuit it through another provider.
    monkeypatch.setenv("ETF_PROVIDER_CHAIN", "yfinance")

    symbols = [f"ETF{i:02d}" for i in range(33)]

    class FakeProvider:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_series(self, series_ids):
            return [
                ProviderResult(
                    provider="yfinance",
                    series_id=symbol,
                    frame=pd.DataFrame(),
                    fetch_error="fixture provider outage",
                )
                for symbol in series_ids
            ]

    monkeypatch.setattr(
        "harvester.providers.etf_yfinance.EtfYfinanceProvider",
        FakeProvider,
    )
    with pytest.raises(RuntimeError, match="no usable rows") as exc_info:
        fetch_recent_ohlcv(symbols, period="5d")

    outcome = exc_info.value.outcome
    assert outcome["status"] == "provider_failed_no_acceptable_fallback"
    assert outcome["requested_count"] == 33
    assert outcome["succeeded_count"] == 0
    assert outcome["failed_count"] == 33
    assert sorted(outcome["failed_series"]) == symbols


def test_staged_provider_outcome_is_identical_across_release_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    import json

    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-09", "2026-07-10"]),
            "symbol": ["SPY", "SPY"],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [100.0, 101.0],
            "volume": [1.0, 1.0],
            "return_1d": [0.0, 0.01],
            "return_5d": [0.0, 0.0],
            "return_20d": [0.0, 0.0],
            "return_60d": [0.0, 0.0],
            "volatility_20d": [0.0, 0.0],
            "drawdown_60d": [0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def outage(symbols, *, period="5d"):
        raise RuntimeError("fixture provider outage")

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", outage)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    release_dir = tmp_path / "release"
    stage_cross_asset_panel(
        release_dir,
        release_id="2026-07-10-r1",
        as_of_date="2026-07-10",
        vintage_date="2026-07-10",
        workspace=workspace,
    )

    manifest = json.loads(
        (release_dir / "manifests" / "cross_asset_daily_panel.manifest.json").read_text()
    )
    provenance = json.loads(
        (release_dir / "provenance" / "cross_asset_daily_panel.provenance.json").read_text()
    )
    quality = json.loads(
        (release_dir / "quality_reports" / "cross_asset_daily_panel.quality.json").read_text()
    )
    expected = manifest["provider_outcome"]
    assert expected["status"] == "reused_after_provider_failure"
    assert provenance["provider_outcome"] == expected
    assert quality["provider_outcome"] == expected


def test_build_retains_existing_when_fetch_raises(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-09", "2026-07-10"]),
            "symbol": ["SPY", "SPY"],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [100.0, 101.0],
            "volume": [1.0, 1.0],
            "return_1d": [0.0, 0.01],
            "return_5d": [0.0, 0.0],
            "return_20d": [0.0, 0.0],
            "return_60d": [0.0, 0.0],
            "volatility_20d": [0.0, 0.0],
            "drawdown_60d": [0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def boom(symbols, *, period="5d"):
        raise RuntimeError("ETF fetch produced no usable rows for 1 symbols (1 failed/empty)")

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", boom)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY"],
    )

    panel, outcome = build_cross_asset_panel(workspace=workspace, return_outcome=True)
    assert len(panel) == 2
    assert panel["close"].iloc[-1] == pytest.approx(101.0)
    assert outcome["status"] == "reused_after_provider_failure"
    assert outcome["failed_count"] == 1


def test_build_merges_by_symbol_date_not_date_only(tmp_path: Path, monkeypatch) -> None:
    """Partial fresh fetch must not delete other symbols on the same dates."""
    workspace = tmp_path / "workspace"
    panel_dir = workspace / "Data" / "panels"
    panel_dir.mkdir(parents=True)
    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-09", "2026-07-09", "2026-07-10", "2026-07-10"]),
            "symbol": ["SPY", "QQQ", "SPY", "QQQ"],
            "open": [1.0, 1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0, 1.0],
            "close": [100.0, 200.0, 101.0, 201.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
            "return_1d": [0.0, 0.0, 0.01, 0.005],
            "return_5d": [0.0, 0.0, 0.0, 0.0],
            "return_20d": [0.0, 0.0, 0.0, 0.0],
            "return_60d": [0.0, 0.0, 0.0, 0.0],
            "volatility_20d": [0.0, 0.0, 0.0, 0.0],
            "drawdown_60d": [0.0, 0.0, 0.0, 0.0],
        }
    )
    seed.to_parquet(panel_dir / "cross_asset_daily_panel.parquet", index=False)

    def fake_fetch(symbols, *, period="5d"):
        # Only SPY refreshes for 2026-07-10; QQQ must be preserved.
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-10"]),
                "symbol": ["SPY"],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [102.0],
                "volume": [1.0],
            }
        )

    monkeypatch.setattr("harvester.cross_asset_panel.fetch_recent_ohlcv", fake_fetch)
    monkeypatch.setattr(
        "harvester.cross_asset_panel.resolve_etf_universe",
        lambda workspace=None: ["SPY", "QQQ"],
    )

    panel = build_cross_asset_panel(workspace=workspace)
    qqq = panel[(panel["symbol"] == "QQQ") & (panel["date"] == pd.Timestamp("2026-07-10"))]
    spy = panel[(panel["symbol"] == "SPY") & (panel["date"] == pd.Timestamp("2026-07-10"))]
    assert len(qqq) == 1
    assert qqq.iloc[0]["close"] == pytest.approx(201.0)
    assert len(spy) == 1
    assert spy.iloc[0]["close"] == pytest.approx(102.0)


def test_sync_panel_writes_mirror_and_tolerates_readonly_canonical(tmp_path: Path) -> None:
    from harvester.cross_asset_panel import sync_panel_to_workspace

    workspace = tmp_path / "workspace"
    latest_data = workspace / "Data" / "harvester" / "exports" / "latest" / "data"
    latest_data.mkdir(parents=True)
    canonical = latest_data / "cross_asset_daily_panel.parquet"
    # Simulate finalized release: present but not writable.
    pd.DataFrame({"date": ["2026-06-04"], "close": [1.0]}).to_parquet(canonical, index=False)
    canonical.chmod(0o444)
    latest_data.chmod(0o555)

    panel = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-10"]),
            "symbol": ["SPY"],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [100.0],
            "volume": [1.0],
            "return_1d": [0.0],
            "return_5d": [0.0],
            "return_20d": [0.0],
            "return_60d": [0.0],
            "volatility_20d": [0.0],
            "drawdown_60d": [0.0],
        }
    )
    mirror = sync_panel_to_workspace(panel, workspace)
    assert mirror.exists()
    assert pd.read_parquet(mirror).iloc[0]["close"] == pytest.approx(100.0)
    # Canonical stays at prior content when read-only.
    assert pd.read_parquet(canonical).iloc[0]["close"] == pytest.approx(1.0)
