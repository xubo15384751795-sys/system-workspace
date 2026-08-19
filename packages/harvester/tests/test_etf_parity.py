from __future__ import annotations

import pandas as pd

from harvester.core.etf_parity import (
    build_provider_parity_report,
    route_policy_for_selection,
)


def _frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=len(values), freq="D"),
            "value": values,
        }
    )


def test_parity_report_is_pending_review_until_explicitly_certified() -> None:
    left = {ticker: _frame([100.0 + i for i in range(20)]) for ticker in ("SPY",)}
    right = {ticker: _frame([100.0 + i for i in range(20)]) for ticker in ("SPY",)}

    report = build_provider_parity_report(
        {"tiingo": left, "massive": right},
        sentinels=("SPY",),
        minimum_overlap_rows=20,
        human_reviewed=False,
        captured_at="2026-08-19T00:00:00Z",
    )

    assert report["status"] == "PARITY_PENDING_REVIEW"
    assert report["certified"] is False
    assert report["promotion_allowed"] is False

    reviewed = build_provider_parity_report(
        {"tiingo": left, "massive": right},
        sentinels=("SPY",),
        minimum_overlap_rows=20,
        human_reviewed=True,
    )
    assert reviewed["status"] == "CERTIFIED"
    assert reviewed["promotion_allowed"] is True


def test_parity_report_flags_value_drift_and_missing_sentinel() -> None:
    report = build_provider_parity_report(
        {
            "tiingo": {"SPY": _frame([100.0, 101.0])},
            "massive": {"SPY": _frame([100.0, 103.0])},
        },
        sentinels=("SPY", "QQQ"),
        minimum_overlap_rows=1,
    )

    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["series"]["SPY"]["status"] == "SOURCE_DRIFT"
    assert report["series"]["QQQ"]["status"] == "NO_DATA"


def test_parity_report_preserves_secret_free_provider_diagnostics() -> None:
    report = build_provider_parity_report(
        {"tiingo": {}, "massive": {}},
        sentinels=("SPY",),
        provider_diagnostics={
            "tiingo": [{"series_id": "SPY", "reason": "transport_error", "error": "DNS failed"}],
            "massive": [{"series_id": "SPY", "reason": "rate_limited", "error": "HTTP 429"}],
        },
    )

    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["provider_diagnostics"]["massive"][0]["reason"] == "rate_limited"
    assert "api_key" not in str(report["provider_diagnostics"]).lower()


def test_yfinance_route_is_always_diagnostic() -> None:
    policy = route_policy_for_selection({"SPY": "yfinance"})

    assert policy["route_class"] == "diagnostic_fallback"
    assert policy["diagnostic_only"] is True
    assert policy["promotion_allowed"] is False


def test_massive_fallback_requires_reviewed_parity() -> None:
    pending = route_policy_for_selection({"SPY": "massive"})
    assert pending["route_class"] == "equivalent_fallback_pending_parity"
    assert pending["decision_usable"] is False

    certified = route_policy_for_selection(
        {"SPY": "massive"},
        parity_report={"certified": True, "status": "CERTIFIED"},
    )
    assert certified["route_class"] == "authoritative_provider_route"
    assert certified["decision_usable"] is True


def test_mixed_authoritative_provider_release_is_not_silent() -> None:
    policy = route_policy_for_selection({"SPY": "tiingo", "QQQ": "massive"})
    assert policy["route_class"] == "mixed_authoritative_provider_release"
    assert policy["diagnostic_only"] is True
