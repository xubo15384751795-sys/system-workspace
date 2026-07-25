"""Content freshness + proxy-quality extraction guards for phase-1 data supply."""
from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import freshness_validator as fv  # noqa: E402

import scripts.commands.weekly.build_proxy_quality_report as bpq  # noqa: E402


def test_trading_days_behind_weekend_uses_friday() -> None:
    # Saturday with panel through Friday → 0 trading days behind
    assert fv.trading_days_behind(date(2026, 7, 10), date(2026, 7, 11)) == 0
    # Monday with panel stuck on prior Monday → 5 trading days
    assert fv.trading_days_behind(date(2026, 6, 1), date(2026, 6, 8)) == 5


def test_content_freshness_reports_stale_and_fresh(tmp_path: Path) -> None:
    stale = tmp_path / "stale.parquet"
    pd.DataFrame({"date": [pd.Timestamp("2026-06-04")], "symbol": ["SPY"]}).to_parquet(stale)
    now = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
    stale_check = fv.check_content_freshness(
        "etf_panel", stale, "date", max_trading_days_behind=3, now=now
    )
    assert stale_check["status"] == "STALE"
    assert stale_check["trading_days_behind"] > 3

    fresh = tmp_path / "fresh.parquet"
    pd.DataFrame({"date": [pd.Timestamp("2026-07-10")], "symbol": ["SPY"]}).to_parquet(fresh)
    fresh_check = fv.check_content_freshness(
        "etf_panel", fresh, "date", max_trading_days_behind=3, now=now
    )
    assert fresh_check["status"] == "FRESH"


def test_proxy_quality_extracts_nonempty_registry() -> None:
    proxies = bpq._extract_registry_metadata()
    assert len(proxies) > 0
    assert bpq.REGISTRY_PATH.name == "_replay_registry.py"
    report = bpq.build_report()
    assert report["summary"]["total"] == len(proxies)
    assert report["summary"]["total"] > 0
    for row in report["proxies"]:
        assert row["quality_tier"] in {
            "CORE_ELIGIBLE",
            "CONSTRUCT_SUPPORT",
            "DIAGNOSTIC_ONLY",
            "BACKGROUND_ONLY",
            "REJECTED",
        }


def test_proxy_quality_fail_fast_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bpq, "_extract_registry_metadata", lambda: [])
    with pytest.raises(RuntimeError, match="proxy quality report empty"):
        bpq.build_report()
