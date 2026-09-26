from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from verity.runtime._daily_observability import publish_daily_run_observability


def test_publish_records_observation_without_changing_outcome(tmp_path: Path) -> None:
    quality_dir = (
        tmp_path
        / "Data"
        / "harvester"
        / "exports"
        / "latest"
        / "quality_reports"
    )
    quality_dir.mkdir(parents=True)
    (quality_dir / "cross_asset_daily_panel.quality.json").write_text(
        '{"generated_at": "2026-08-24T01:00:00Z", "data_contract": {"status": "PASS", "mode": "shadow", "enforced": false}}',
        encoding="utf-8",
    )
    outcome = {
        "run_id": "daily-obs-1",
        "status": "success",
        "exit_code": 0,
        "operational_state": "SYSTEM_OK",
    }
    result = publish_daily_run_observability(
        outcome,
        output_root=tmp_path / "Output",
        source="launchd",
        workspace_root=tmp_path,
        observed_at=datetime(2026, 8, 24, 1, 0, tzinfo=UTC),
    )
    observation = result["data_contract_observation"]
    assert outcome["exit_code"] == 0
    assert observation["mode"] == "shadow"
    assert observation["enforce_changed"] is False
    assert observation["consecutive_clean_days"] == 1
    assert (tmp_path / "Output" / "state" / "health" / "data_contract_observation.json").is_file()
