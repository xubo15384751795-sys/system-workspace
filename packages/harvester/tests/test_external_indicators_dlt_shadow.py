"""Offline tests for the cache-only normalized-series dlt operator."""
from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pandas as pd
import pytest

import harvester.operators.run_external_indicators_dlt_shadow as shadow
from harvester.providers.external_indicators import ExternalIndicator


def test_run_shadow_reads_cache_and_never_fetches(tmp_path: Path, monkeypatch) -> None:
    indicator = ExternalIndicator(
        name="TEST_SERIES",
        series_id="TEST_SERIES",
        description="fixture",
        publisher_url="https://example.invalid/provider",
        instructions="fixture only",
    )
    cached = pd.Series(
        [2.0, 1.0],
        index=pd.to_datetime(["2026-08-19", "2026-08-18"]),
        name=indicator.series_id,
    )
    calls: list[tuple[str, Path]] = []

    def fake_read_cache(item, *, cache_dir: Path):
        calls.append((item.series_id, cache_dir))
        return cached

    monkeypatch.setattr(shadow, "KNOWN_INDICATORS", (indicator,))
    monkeypatch.setattr(shadow, "read_cached_external_indicator", fake_read_cache)

    report = shadow.run_shadow(
        cache_dir=tmp_path / "cache",
        database_path=tmp_path / "shadow.duckdb",
    )

    assert calls == [("TEST_SERIES", (tmp_path / "cache").resolve())]
    assert report["status"] == "MATCH"
    assert report["authority"] == "shadow_only"
    assert report["promotion_allowed"] is False
    assert report["series"]["TEST_SERIES"]["status"] == "MATCH"


def test_run_shadow_marks_missing_cache_without_creating_release_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    indicator = ExternalIndicator(
        name="MISSING_SERIES",
        series_id="MISSING_SERIES",
        description="fixture",
        publisher_url="https://example.invalid/provider",
        instructions="fixture only",
    )
    monkeypatch.setattr(shadow, "KNOWN_INDICATORS", (indicator,))
    monkeypatch.setattr(
        shadow,
        "read_cached_external_indicator",
        lambda *_args, **_kwargs: None,
    )

    report = shadow.run_shadow(
        cache_dir=tmp_path / "cache",
        database_path=tmp_path / "shadow.duckdb",
    )

    assert report["status"] == "NO_DATA"
    assert report["series"]["MISSING_SERIES"]["status"] == "MISSING_CACHE"
    assert report["promotion_allowed"] is False


def test_run_shadow_reuses_persistent_cursor_without_duplicate_load(
    tmp_path: Path, monkeypatch
) -> None:
    indicator = ExternalIndicator(
        name="PERSISTENT_SERIES",
        series_id="PERSISTENT_SERIES",
        description="fixture",
        publisher_url="https://example.invalid/provider",
        instructions="fixture only",
    )
    cached = pd.Series(
        [2.0, 1.0],
        index=pd.to_datetime(["2026-08-19", "2026-08-18"]),
        name=indicator.series_id,
    )
    monkeypatch.setattr(shadow, "KNOWN_INDICATORS", (indicator,))
    monkeypatch.setattr(
        shadow,
        "read_cached_external_indicator",
        lambda *_args, **_kwargs: cached,
    )
    database = tmp_path / "persistent.duckdb"

    first = shadow.run_shadow(cache_dir=tmp_path / "cache", database_path=database)
    second = shadow.run_shadow(cache_dir=tmp_path / "cache", database_path=database)

    assert first["status"] == second["status"] == "MATCH"
    with duckdb.connect(str(database), read_only=True) as connection:
        row_count = connection.execute(
            "SELECT count(*) FROM external_indicators_shadow.external_persistent_series"
        ).fetchone()[0]
        load_count = connection.execute(
            "SELECT count(*) FROM external_indicators_shadow._dlt_loads"
        ).fetchone()[0]
    assert row_count == 2
    assert load_count == 1


def test_run_shadow_can_emit_capture_backed_idempotence_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    indicator = ExternalIndicator(
        name="CAPTURED_SERIES",
        series_id="CAPTURED_SERIES",
        description="fixture",
        publisher_url="https://example.invalid/provider",
        instructions="fixture only",
    )
    cached = pd.Series(
        [2.0, 1.0],
        index=pd.to_datetime(["2026-08-25", "2026-08-24"]),
        name=indicator.series_id,
    )
    monkeypatch.setattr(shadow, "KNOWN_INDICATORS", (indicator,))
    monkeypatch.setattr(
        shadow,
        "read_cached_external_indicator",
        lambda *_args, **_kwargs: cached,
    )
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "captured_series.csv"
    cache_file.write_text("date,value\n2026-08-24,1.0\n2026-08-25,2.0\n", encoding="utf-8")
    cache_digest = hashlib.sha256(cache_file.read_bytes()).hexdigest()

    report = shadow.run_shadow(
        cache_dir=cache_dir,
        database_path=tmp_path / "captured.duckdb",
        capture_manifest={
            "schema_version": "system.harvester.provider_capture.v1",
            "capture_id": "captured-2026-08-25",
            "capture_kind": "daily_provider_capture",
            "provider": "external_indicators",
            "observation_date": "2026-08-25",
            "captured_at": "2026-08-25T07:30:00+00:00",
            "payload_digests": {"CAPTURED_SERIES": cache_digest},
        },
        verify_idempotence=True,
    )

    assert report["status"] == "MATCH"
    assert report["observation_date"] == "2026-08-25"
    assert report["capture"]["capture_id"] == "captured-2026-08-25"
    assert report["payload_digest_verified"] is True
    assert report["incremental_state"]["state_persisted"] is True
    assert report["incremental_state"]["idempotence_verified"] is True


def test_run_shadow_rejects_database_name_equal_to_dataset(
    tmp_path: Path, monkeypatch
) -> None:
    indicator = ExternalIndicator(
        name="NAME_COLLISION",
        series_id="NAME_COLLISION",
        description="fixture",
        publisher_url="https://example.invalid/provider",
        instructions="fixture only",
    )
    monkeypatch.setattr(shadow, "KNOWN_INDICATORS", (indicator,))
    monkeypatch.setattr(
        shadow,
        "read_cached_external_indicator",
        lambda *_args, **_kwargs: pd.Series(
            [1.0], index=pd.to_datetime(["2026-08-25"]), name=indicator.series_id
        ),
    )

    with pytest.raises(ValueError, match="database filename must differ"):
        shadow.run_shadow(
            cache_dir=tmp_path / "cache",
            database_path=tmp_path / "external_indicators_shadow.duckdb",
        )
