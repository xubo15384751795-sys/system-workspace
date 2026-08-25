"""Offline tests for the generic normalized-series dlt shadow source."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest
from harvester.ingestion.dlt_series_source import (
    DLT_MAX_ATTEMPTS,
    external_indicator_source,
    normalized_series_rows,
    run_dlt_with_retry,
    series_table_name,
)


def _series(values: tuple[float, ...] = (1.0, 2.0)) -> pd.Series:
    return pd.Series(
        values,
        index=pd.to_datetime(["2026-08-18", "2026-08-19"][: len(values)]),
        name="CISS",
    )


@pytest.fixture()
def shadow_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dlt

    monkeypatch.chdir(tmp_path)
    return dlt.pipeline(
        pipeline_name="external_series_shadow_test",
        dataset_name="external_series_dataset",
        destination=dlt.destinations.duckdb(str(tmp_path / "shadow.duckdb")),
        pipelines_dir=str(tmp_path / "pipelines"),
    )


def test_normalized_series_rows_are_sorted_and_typed() -> None:
    series = pd.Series(
        [2, 1, "bad"],
        index=pd.to_datetime(["2026-08-19", "2026-08-18", "2026-08-17"]),
    )

    rows = normalized_series_rows(series)

    assert rows == (
        {"date": pd.Timestamp("2026-08-18").date(), "value": 1.0},
        {"date": pd.Timestamp("2026-08-19").date(), "value": 2.0},
    )


def test_duplicate_normalized_date_is_blocked() -> None:
    series = pd.Series(
        [1.0, 2.0],
        index=pd.to_datetime(["2026-08-18T00:00:00", "2026-08-18T12:00:00"]),
    )

    with pytest.raises(ValueError, match="duplicate date keys"):
        normalized_series_rows(series)


def test_series_table_name_is_safe_and_deterministic() -> None:
    assert series_table_name("123/FRED CISS") == "external_series_123_fred_ciss"


def test_series_source_uses_incremental_cursor_and_freeze_contract(
    shadow_pipeline, tmp_path: Path
) -> None:
    shadow_pipeline.run(external_indicator_source("CISS", _series()))
    shadow_pipeline.run(external_indicator_source("CISS", _series((1.0, 2.0))))

    with duckdb.connect(str(tmp_path / "shadow.duckdb"), read_only=True) as connection:
        frame = connection.sql(
            "SELECT date, value FROM external_series_dataset.external_ciss ORDER BY date"
        ).df()
    assert len(frame) == 2
    assert frame["value"].tolist() == pytest.approx([1.0, 2.0])

    table = shadow_pipeline.default_schema.get_table("external_ciss")
    assert table["columns"]["date"]["data_type"] == "date"
    assert table["columns"]["value"]["data_type"] == "double"
    assert table["schema_contract"] == {"columns": "freeze", "data_type": "freeze"}


@pytest.mark.parametrize("strategy", ["evolve", "freeze", "discard"])
def test_series_source_registers_all_contract_strategies(shadow_pipeline, strategy: str) -> None:
    shadow_pipeline.run(
        external_indicator_source("H41_PRIMARY_CREDIT", _series(), schema_contract=strategy)
    )

    table = shadow_pipeline.default_schema.get_table("external_h41_primary_credit")
    dlt_strategy = "discard_value" if strategy == "discard" else strategy
    assert table["schema_contract"] == {
        "columns": dlt_strategy,
        "data_type": dlt_strategy,
    }


def test_series_source_rejects_unknown_contract_strategy() -> None:
    with pytest.raises(ValueError, match="unsupported schema contract strategy"):
        list(external_indicator_source("CISS", _series(), schema_contract="unknown"))


def test_dlt_load_retries_with_bounded_exponential_backoff() -> None:
    class Pipeline:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, source):
            del source
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError("transient load failure")
            return "loaded"

    delays: list[float] = []
    pipeline = Pipeline()
    result, attempts = run_dlt_with_retry(
        pipeline,
        lambda: object(),
        max_attempts=DLT_MAX_ATTEMPTS,
        backoff_seconds=2.0,
        sleep_fn=delays.append,
    )

    assert result == "loaded"
    assert attempts == 3
    assert pipeline.calls == 3
    assert delays == [2.0, 4.0]
