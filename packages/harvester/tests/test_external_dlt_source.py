"""Offline shadow-pilot tests for harvester.ingestion.external_dlt_source.

Runs the dlt CFTC shadow resource against a local duckdb destination inside
tmp_path. No network access; payloads are fabricated Socrata-shaped JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from harvester.ingestion.external_dlt_source import (
    SHADOW_TABLE_NAME,
    build_cftc_shadow_parity_report,
    cftc_cot_source,
    write_cftc_shadow_parity_report,
)
from harvester.providers.external_indicators import _parse_cftc_tff_lev_sp

FIXTURE_ROWS = [
    {
        "report_date_as_yyyy_mm_dd": "2026-08-04T00:00:00.000",
        "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "lev_money_positions_long": "1000",
        "lev_money_positions_short": "400",
    },
    {
        # Duplicate report date (second expiry): legacy path SUMS these.
        "report_date_as_yyyy_mm_dd": "2026-08-04T00:00:00.000",
        "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "lev_money_positions_long": "1200",
        "lev_money_positions_short": "450",
    },
    {
        "report_date_as_yyyy_mm_dd": "2026-08-11T00:00:00.000",
        "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "lev_money_positions_long": "900",
        "lev_money_positions_short": "500",
    },
]

FIXTURE_JSON = json.dumps(FIXTURE_ROWS)

EXPECTED_VALUES = {
    pd.Timestamp("2026-08-04").date(): (1000 - 400) + (1200 - 450),
    pd.Timestamp("2026-08-11").date(): 900 - 500,
}

DATASET_NAME = "cftc_shadow_dataset"


@pytest.fixture()
def shadow_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import dlt

    # Any relative write (including dlt's own working-dir state) lands in tmp_path.
    monkeypatch.chdir(tmp_path)
    pipeline = dlt.pipeline(
        pipeline_name="cftc_cot_shadow_test",
        dataset_name=DATASET_NAME,
        destination=dlt.destinations.duckdb(str(tmp_path / "shadow.duckdb")),
        pipelines_dir=str(tmp_path / "pipelines"),
    )
    return pipeline


def _connect(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(tmp_path / "shadow.duckdb"), read_only=True)


def _shadow_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.sql(
        f'SELECT date, value FROM {DATASET_NAME}.{SHADOW_TABLE_NAME} ORDER BY date'
    ).df()


def test_loaded_rows_match_legacy_normalization(shadow_pipeline, tmp_path: Path) -> None:
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))

    frame = _shadow_frame(_connect(tmp_path))
    assert len(frame) == len(EXPECTED_VALUES)

    legacy = _parse_cftc_tff_lev_sp(FIXTURE_JSON)
    for _, row in frame.iterrows():
        day = row["date"].date() if hasattr(row["date"], "date") else row["date"]
        assert day in EXPECTED_VALUES
        assert float(row["value"]) == pytest.approx(float(legacy[pd.Timestamp(day)]))


def test_duplicate_dates_aggregated_like_legacy(shadow_pipeline, tmp_path: Path) -> None:
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))
    frame = _shadow_frame(_connect(tmp_path))
    duplicated_day = pd.Timestamp("2026-08-04").date()
    observed = frame.loc[
        frame["date"].map(lambda value: value.date() if hasattr(value, "date") else value)
        == duplicated_day,
        "value",
    ]
    assert len(observed) == 1
    assert float(observed.iloc[0]) == pytest.approx(float(EXPECTED_VALUES[duplicated_day]))


def test_incremental_second_run_appends_nothing(shadow_pipeline, tmp_path: Path) -> None:
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))
    first_count = len(_shadow_frame(_connect(tmp_path)))
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))
    second_count = len(_shadow_frame(_connect(tmp_path)))
    assert first_count == second_count == len(EXPECTED_VALUES)


def test_loaded_columns_and_types(shadow_pipeline, tmp_path: Path) -> None:
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))
    con = _connect(tmp_path)
    columns = con.sql(
        "SELECT column_name, data_type FROM information_schema.columns "
        f"WHERE table_schema = '{DATASET_NAME}' AND table_name = '{SHADOW_TABLE_NAME}'"
    ).df()
    user_columns = set(columns["column_name"]) - {"_dlt_id", "_dlt_load_id"}
    assert user_columns == {"date", "value"}
    types = dict(zip(columns["column_name"], columns["data_type"]))
    assert types["date"].upper() == "DATE"
    assert types["value"].upper() in {"DOUBLE", "FLOAT8"}


def test_freeze_schema_contract_registered(shadow_pipeline) -> None:
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))
    table = shadow_pipeline.default_schema.get_table(SHADOW_TABLE_NAME)
    assert table["columns"]["date"]["data_type"] == "date"
    assert table["columns"]["date"]["nullable"] is False
    assert table["columns"]["value"]["data_type"] == "double"
    assert table["columns"]["value"]["nullable"] is False
    contract = table.get("schema_contract") or {}
    assert contract.get("columns") == "freeze"
    assert contract.get("data_type") == "freeze"


def test_freeze_rejects_type_drift(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A payload that cannot coerce into the frozen double column fails the load."""
    import dlt

    monkeypatch.chdir(tmp_path)
    pipeline = dlt.pipeline(
        pipeline_name="cftc_cot_drift_test",
        dataset_name=DATASET_NAME,
        destination=dlt.destinations.duckdb(str(tmp_path / "drift.duckdb")),
        pipelines_dir=str(tmp_path / "pipelines"),
    )
    pipeline.run(cftc_cot_source(FIXTURE_JSON))

    @dlt.resource(
        name=SHADOW_TABLE_NAME,
        primary_key="date",
        write_disposition="append",
        columns={
            "date": {"data_type": "date", "nullable": False},
            "value": {"data_type": "double", "nullable": False},
        },
        schema_contract={"columns": "freeze", "data_type": "freeze"},
    )
    def drifted_rows():
        yield {"date": pd.Timestamp("2026-08-18").date(), "value": "not-a-number"}

    with pytest.raises(Exception):
        pipeline.run(drifted_rows)

    con = duckdb.connect(str(tmp_path / "drift.duckdb"), read_only=True)
    frame = con.sql(
        f'SELECT date, value FROM {DATASET_NAME}.{SHADOW_TABLE_NAME} ORDER BY date'
    ).df()
    assert len(frame) == len(EXPECTED_VALUES)


def test_no_writes_outside_tmp_path(shadow_pipeline, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(tmp_path)
    shadow_pipeline.run(cftc_cot_source(FIXTURE_JSON))

    assert (tmp_path / "shadow.duckdb").exists()
    assert (tmp_path / "pipelines").exists()
    assert not (repo_root / ".dlt").exists()
    assert not (repo_root / "shadow.duckdb").exists()


def test_parity_report_matches_legacy_parser_and_is_shadow_only() -> None:
    report = build_cftc_shadow_parity_report(FIXTURE_JSON)

    assert report["status"] == "MATCH"
    assert report["execution_parity"] == "MATCH"
    assert report["authority"] == "shadow_only"
    assert report["promotion_allowed"] is False
    assert report["legacy_row_count"] == report["dlt_shadow_row_count"] == 2
    assert report["missing_in_shadow"] == []
    assert report["extra_in_shadow"] == []
    assert report["value_mismatches"] == []


def test_parity_report_exposes_value_drift_without_promoting_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "harvester.ingestion.external_dlt_source._shadow_cftc_series",
        lambda _payload: pd.Series(
            [1350.5, 400.0],
            index=pd.to_datetime(["2026-08-04", "2026-08-11"]),
            name="CFTC_TFF_LEV_SP",
        ),
    )

    report = build_cftc_shadow_parity_report(FIXTURE_JSON)

    assert report["status"] == "MISMATCH"
    assert report["value_mismatches"] == [
        {
            "date": "2026-08-04",
            "legacy": 1350.0,
            "dlt_shadow": 1350.5,
        }
    ]
    assert report["promotion_allowed"] is False


def test_parity_report_writer_replaces_target_atomically(tmp_path: Path) -> None:
    output_path = tmp_path / "health" / "cftc_dlt_parity.json"

    report = write_cftc_shadow_parity_report(FIXTURE_JSON, output_path)

    assert output_path.is_file()
    assert json.loads(output_path.read_text(encoding="utf-8")) == report
    assert not list(output_path.parent.glob("*.tmp"))
