from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from harvester.operators.aggregate_dlt_shadow_window import evaluate_window


def _payload(day: str, *, status: str = "MATCH", capture_id: str | None = None) -> dict:
    return {
        "schema_version": "system.harvester_dlt_series_shadow.v1",
        "authority": "shadow_only",
        "promotion_allowed": False,
        "status": status,
        "observation_date": day,
        "observed_at": f"{day}T08:00:00+00:00",
        "provider": "external_indicators",
        "schema_contract": "freeze",
        "payload_digest_verified": True,
        "capture": {
            "schema_version": "system.harvester.provider_capture.v1",
            "capture_id": capture_id or f"capture-{day}",
            "capture_kind": "daily_provider_capture",
            "captured_at": f"{day}T07:30:00+00:00",
        },
        "incremental_state": {
            "state_persisted": True,
            "idempotence_verified": True,
        },
        "series": {
            "CISS": {"status": "MATCH"},
            "OFR_FINANCIAL_STRESS": {"status": "MATCH"},
        },
    }


def _write_reports(tmp_path: Path, count: int = 7) -> list[Path]:
    start = date(2026, 8, 19)
    paths: list[Path] = []
    for offset in range(count):
        day = (start + timedelta(days=offset)).isoformat()
        path = tmp_path / f"dlt-{day}.json"
        path.write_text(json.dumps(_payload(day)), encoding="utf-8")
        paths.append(path)
    return paths


def test_real_capture_window_requires_seven_consecutive_matches(tmp_path: Path) -> None:
    report = evaluate_window(_write_reports(tmp_path))

    assert report["status"] == "MATCH"
    assert report["observation_count"] == 7
    assert report["promotion_allowed"] is False


def test_cache_only_or_missing_incremental_evidence_cannot_pass(tmp_path: Path) -> None:
    paths = _write_reports(tmp_path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload.pop("capture")
    payload["incremental_state"] = {"state_persisted": True}
    paths[0].write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_window(paths)

    assert report["status"] == "INCOMPLETE"
    assert report["reason"] == "observation_missing_real_capture_or_incremental_evidence"
    assert paths[0].as_posix() in report["unsafe_entries"]


def test_missing_date_is_not_a_complete_window(tmp_path: Path) -> None:
    paths = _write_reports(tmp_path)
    paths[2].unlink()

    report = evaluate_window(paths[:2] + paths[3:])

    assert report["status"] == "INCOMPLETE"
    assert report["reason"] == "observation_window_short"


def test_series_drift_is_a_mismatch(tmp_path: Path) -> None:
    paths = _write_reports(tmp_path)
    payload = json.loads(paths[-1].read_text(encoding="utf-8"))
    payload["series"]["CISS"] = {"status": "MATCH"}
    payload["series"]["NEW_SERIES"] = {"status": "MATCH"}
    paths[-1].write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_window(paths)

    assert report["status"] == "MISMATCH"
    assert report["reason"] == "parity_mismatch_or_schema_identity_drift"


def test_observed_at_must_match_observation_date_in_utc(tmp_path: Path) -> None:
    paths = _write_reports(tmp_path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["observed_at"] = "2026-08-20T08:30:00+08:00"
    paths[0].write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_window(paths)

    assert report["status"] == "INCOMPLETE"
    assert paths[0].as_posix() in report["unsafe_entries"]


def test_duplicate_capture_id_is_not_a_window_observation(tmp_path: Path) -> None:
    paths = _write_reports(tmp_path)
    payload = json.loads(paths[-1].read_text(encoding="utf-8"))
    payload["capture"]["capture_id"] = "capture-2026-08-19"
    paths[-1].write_text(json.dumps(payload), encoding="utf-8")

    report = evaluate_window(paths)

    assert report["status"] == "INCOMPLETE"
    assert report["reason"] == "duplicate_capture_ids"
