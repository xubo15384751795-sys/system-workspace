"""Canonical freshness digest must survive all local adapter boundaries."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from dagster import build_op_context
from orchestration.ops import refresh_chain  # noqa: E402

import scripts.freshness_validator as freshness_validator  # noqa: E402
from scripts._admission_gate import admit_for_consumption  # noqa: E402


def test_freshness_validator_admission_and_dagster_share_fixture_digest(
    tmp_path: Path, monkeypatch
) -> None:
    panel = tmp_path / "fixture.parquet"
    pd.DataFrame(
        {"date": [pd.Timestamp("2026-08-10"), pd.Timestamp("2026-08-11")], "value": [1.0, 2.0]}
    ).to_parquet(panel)
    freshness_spec = {
        "fixture_clock": {
            "path": str(panel),
            "date_column": "date",
            "max_trading_days_behind": 3,
        }
    }
    monkeypatch.setattr(freshness_validator, "CONTENT_FRESHNESS", freshness_spec)
    monkeypatch.setattr("scripts._admission_gate._PUBLIC_CONTENT_CHECKS", ("fixture_clock",))
    monkeypatch.setattr(
        "scripts._admission_gate._release_level_blockers", lambda _release: ([], {})
    )
    monkeypatch.setattr("scripts._admission_gate._environmentally_blocked", dict)

    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    direct = freshness_validator.check_content_freshness(
        "fixture_clock", panel, "date", max_trading_days_behind=3, now=now
    )
    decision = admit_for_consumption("refresh_current", release_dir=tmp_path, now=now)
    assert decision.allowed is True
    assert decision.content_checks[0]["result_digest"] == direct["result_digest"]
    assert decision.content_result_digests == [direct["result_digest"]]

    monkeypatch.setattr(refresh_chain, "admit_for_consumption", lambda _consumer: decision)
    dagster_result = refresh_chain.refresh_admission_op(build_op_context())
    assert dagster_result["content_result_digests"] == [direct["result_digest"]]
    assert dagster_result["freshness_digest"] == decision.freshness_digest
