"""Offline operator tests for the CFTC dlt shadow parity path."""
from __future__ import annotations

import pytest

pytest.importorskip("dlt")

import hashlib
import json
from pathlib import Path

from harvester.operators.run_cftc_dlt_shadow_parity import run_cftc_dlt_shadow


PAYLOAD = [
    {
        "report_date_as_yyyy_mm_dd": "2026-08-25T00:00:00.000",
        "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "lev_money_positions_long": "1000",
        "lev_money_positions_short": "400",
    },
    {
        "report_date_as_yyyy_mm_dd": "2026-08-25T00:00:00.000",
        "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
        "lev_money_positions_long": "1200",
        "lev_money_positions_short": "450",
    },
]


def _manifest(*, payload_sha256: str | None = None) -> dict[str, str]:
    manifest = {
        "schema_version": "system.harvester.provider_capture.v1",
        "capture_id": "cftc-2026-08-25",
        "capture_kind": "daily_provider_capture",
        "provider": "cftc",
        "observation_date": "2026-08-25",
        "captured_at": "2026-08-25T08:00:00+00:00",
    }
    if payload_sha256 is not None:
        manifest["payload_sha256"] = payload_sha256
    return manifest


def test_cftc_pure_operator_remains_available_without_dlt_destination() -> None:
    report = run_cftc_dlt_shadow(PAYLOAD)

    assert report["status"] == "MATCH"
    assert report["execution_parity"] == "MATCH"
    assert report["incremental_state"]["idempotence_verified"] is False
    assert report["promotion_allowed"] is False


def test_cftc_operator_records_dlt_execution_and_idempotence(
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "cftc.json"
    payload_path.write_text(json.dumps(PAYLOAD), encoding="utf-8")
    payload_sha256 = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    report = run_cftc_dlt_shadow(
        PAYLOAD,
        database_path=tmp_path / "cftc.duckdb",
        capture_manifest=_manifest(payload_sha256=payload_sha256),
        payload_path=payload_path,
        verify_idempotence=True,
    )

    assert report["status"] == "MATCH"
    assert report["dlt_execution"]["status"] == "MATCH"
    assert report["capture"]["capture_id"] == "cftc-2026-08-25"
    assert report["observation_date"] == "2026-08-25"
    assert report["payload_digest_verified"] is True
    assert report["incremental_state"]["state_persisted"] is True
    assert report["incremental_state"]["idempotence_verified"] is True
    assert report["incremental_state"]["load_count_before"] == report["incremental_state"]["load_count_after"]
