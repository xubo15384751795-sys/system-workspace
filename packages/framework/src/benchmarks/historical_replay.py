"""Historical replay benchmarks — research only, not active pipeline.

HTTP status: research_only_non_harvester
"""
from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path
import ssl
import subprocess
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from src.benchmarks.institutional_risk import DEFAULT_RISK_POLICY, RiskPolicy, action_tier, apply_risk_policy, max_state, rolling_robust_zscore


FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
DEFAULT_SERIES = ["VIXCLS", "BAA10Y", "NFCI"]
CREDIT_SPREAD_CANDIDATES = ("BAMLH0A0HYM2", "BAA10Y", "BAMLC0A0CM", "BAMLC0A4CBBB", "AAA10Y")
COMPARISON_INDICATORS = [
    "joint_structural",
    "institutional_macro_stack",
    "institutional_fast_alert",
    "vix_only",
    "spread_only",
    "liquidity_only",
]
STATE_INDICATORS = ["joint_structural", "institutional_macro_stack", "institutional_fast_alert"]


@dataclass(frozen=True)
class HistoricalCase:
    name: str
    start: str
    end: str
    event_date: str
    description: str


DEFAULT_CASES: tuple[HistoricalCase, ...] = (
    HistoricalCase(
        name="ltcm_1998",
        start="1997-01-01",
        end="1998-12-31",
        event_date="1998-09-23",
        description="LTCM rescue coordination window.",
    ),
    HistoricalCase(
        name="cdo_credit_break_2007",
        start="2006-01-01",
        end="2008-03-31",
        event_date="2007-07-31",
        description="Structured-credit/CDO stress break window.",
    ),
    HistoricalCase(
        name="lehman_2008",
        start="2006-01-01",
        end="2009-06-30",
        event_date="2008-09-15",
        description="Lehman bankruptcy and full-system crisis window.",
    ),
    HistoricalCase(
        name="eurozone_2011",
        start="2010-01-01",
        end="2012-06-30",
        event_date="2011-11-09",
        description="Eurozone sovereign stress and Italian yield pressure window.",
    ),
    HistoricalCase(
        name="china_deval_2015",
        start="2014-01-01",
        end="2016-03-31",
        event_date="2015-08-11",
        description="China RMB devaluation and global risk-off window.",
    ),
    HistoricalCase(
        name="treasury_basis_2020",
        start="2019-01-01",
        end="2020-06-30",
        event_date="2020-03-12",
        description="Treasury basis and market-functioning stress window.",
    ),
    HistoricalCase(
        name="ldi_2022",
        start="2021-01-01",
        end="2023-03-31",
        event_date="2022-09-28",
        description="UK LDI gilt-market stress and Bank of England intervention window.",
    ),
    HistoricalCase(
        name="svb_2023",
        start="2022-01-01",
        end="2023-06-30",
        event_date="2023-03-10",
        description="SVB closure and regional-bank funding stress window.",
    ),
)


def fetch_fred_graph_series(series_id: str, timeout_sec: int = 90, cache_dir: str | Path = "data/raw/fred") -> pd.Series:
    cache_path = Path(cache_dir) / f"{series_id}.csv"
    if cache_path.exists():
        csv_text = cache_path.read_text(encoding="utf-8")
    else:
        csv_text = _download_fred_graph_csv(series_id, timeout_sec)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(csv_text, encoding="utf-8")
    return _parse_fred_graph_csv(series_id, csv_text)


def _download_fred_graph_csv(series_id: str, timeout_sec: int) -> str:
    url = FRED_GRAPH_URL.format(series_id=series_id)
    try:
        completed = subprocess.run(
            ["curl", "-fsSL", "--max-time", str(timeout_sec), url],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout
    except Exception:
        req = Request(url=url, headers={"User-Agent": "StructuralDeformationResearch/0.1"}, method="GET")
        with urlopen(req, timeout=timeout_sec, context=_ssl_context()) as resp:  # nosec B310
            return resp.read().decode("utf-8")


def _parse_fred_graph_csv(series_id: str, csv_text: str) -> pd.Series:
    frame = pd.read_csv(StringIO(csv_text))
    if "observation_date" not in frame.columns or series_id not in frame.columns:
        raise ValueError(f"Unexpected FRED graph CSV schema for {series_id}")
    series = pd.to_numeric(frame[series_id], errors="coerce")
    series.index = pd.to_datetime(frame["observation_date"], errors="coerce")
    series = series[~series.index.isna()].dropna().sort_index()
    series.name = series_id
    return series


def _ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def fetch_default_fred_frame(series_ids: list[str] | None = None) -> pd.DataFrame:
    selected = series_ids or DEFAULT_SERIES
    series = [fetch_fred_graph_series(sid) for sid in selected]
    return pd.concat(series, axis=1).sort_index()


def weekly_frame(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    work = frame.copy()
    work.index = pd.to_datetime(work.index, errors="coerce")
    work = work[~work.index.isna()].sort_index()
    work = work.loc[pd.to_datetime(start) : pd.to_datetime(end)]
    return work.resample("W-FRI").last().ffill()


def rolling_zscore(series: pd.Series, window: int = 52, min_periods: int = 26, robust: bool = False) -> pd.Series:
    if robust:
        return rolling_robust_zscore(series, window=window, min_periods=min_periods)
    numeric = pd.to_numeric(series, errors="coerce")
    mean = numeric.rolling(window=window, min_periods=min_periods).mean().shift(1)
    std = numeric.rolling(window=window, min_periods=min_periods).std(ddof=0).shift(1)
    z = (numeric - mean) / std.replace(0.0, np.nan)
    return z.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def build_structural_signals(
    frame: pd.DataFrame,
    z_window: int = 52,
    robust: bool = False,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
) -> pd.DataFrame:
    required = {"VIXCLS", "NFCI"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing required series: {', '.join(sorted(missing))}")
    credit_col = _first_present(frame, CREDIT_SPREAD_CANDIDATES)
    if credit_col is None:
        raise ValueError("Missing required credit spread series: one of " + ", ".join(CREDIT_SPREAD_CANDIDATES))

    series = ("VIXCLS", credit_col, "NFCI")
    z = pd.DataFrame({col: rolling_zscore(frame[col], window=z_window, robust=robust) for col in series}, index=frame.index)
    stress = z.clip(lower=0.0)

    out = pd.DataFrame(index=frame.index)
    out["M"] = stress[[credit_col, "NFCI"]].mean(axis=1)
    out["D"] = -stress[["NFCI", "VIXCLS"]].mean(axis=1)
    out["K"] = stress["VIXCLS"]
    out["X"] = stress[[credit_col, "NFCI"]].mean(axis=1)
    out["joint_structural"] = pd.concat([out["M"], -out["D"], out["K"], out["X"]], axis=1).mean(axis=1)
    out["vix_only"] = stress["VIXCLS"]
    out["spread_only"] = stress[credit_col]
    out["liquidity_only"] = stress["NFCI"]
    out["institutional_macro_stack"] = (
        0.30 * out["vix_only"]
        + 0.30 * out["liquidity_only"]
        + 0.25 * out["spread_only"]
        + 0.15 * stress["NFCI"]
    )
    out["institutional_fast_alert"] = out[["vix_only", "spread_only", "liquidity_only"]].max(axis=1)
    return apply_risk_policy(out, STATE_INDICATORS, policy=risk_policy)


def _first_present(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in frame.columns and pd.to_numeric(frame[candidate], errors="coerce").notna().any():
            return candidate
    return None


def backtest_warning_metrics(
    signals: pd.DataFrame,
    case: HistoricalCase,
    threshold: float = 1.5,
    lookback_days: int = 365,
    false_positive_gap_days: int = 180,
) -> pd.DataFrame:
    event_date = pd.to_datetime(case.event_date)
    start = pd.to_datetime(case.start)
    pre_start = max(start, event_date - pd.Timedelta(days=lookback_days))
    pre_event = signals.loc[pre_start:event_date]
    false_positive_window = signals.loc[start : event_date - pd.Timedelta(days=false_positive_gap_days)]
    rows: list[dict[str, object]] = []

    for name in COMPARISON_INDICATORS:
        series = signals[name].dropna()
        pre = pre_event[name].dropna()
        warnings = pre[pre >= threshold]
        first_warning = warnings.index.min() if not warnings.empty else pd.NaT
        lead_days = int((event_date - first_warning).days) if pd.notna(first_warning) else None
        false_window = false_positive_window[name].dropna()
        false_positive_rate = float((false_window >= threshold).mean()) if not false_window.empty else 0.0
        pre_coverage = float((pre >= threshold).mean()) if not pre.empty else 0.0
        event_idx = _event_observation_index(series, event_date)
        rows.append(
            {
                "case": case.name,
                "indicator": name,
                "event_date": event_date.date().isoformat(),
                "threshold": threshold,
                "first_warning": first_warning.date().isoformat() if pd.notna(first_warning) else None,
                "lead_days": lead_days,
                "pre_event_coverage": pre_coverage,
                "false_positive_rate": false_positive_rate,
                "peak_pre_event": float(pre.max()) if not pre.empty else 0.0,
                "event_value": float(series.loc[event_idx]) if event_idx is not None else 0.0,
            }
        )
    return pd.DataFrame.from_records(rows)


def backtest_state_metrics(
    signals: pd.DataFrame,
    case: HistoricalCase,
    lookback_days: int = 365,
    false_positive_gap_days: int = 180,
    event_confirmation_days: int = 21,
) -> pd.DataFrame:
    event_date = pd.to_datetime(case.event_date)
    start = pd.to_datetime(case.start)
    actionable_states = ["RISK_OFF", "CRISIS"]
    pre_start = max(start, event_date - pd.Timedelta(days=lookback_days))
    pre_event = signals.loc[pre_start:event_date]
    false_positive_window = signals.loc[start : event_date - pd.Timedelta(days=false_positive_gap_days)]
    rows: list[dict[str, object]] = []

    for name in STATE_INDICATORS:
        state_col = f"{name}_state"
        if state_col not in signals.columns:
            continue
        pre_states = pre_event[state_col].dropna()
        warning_states = pre_states[pre_states.isin(actionable_states)]
        first_warning = warning_states.index.min() if not warning_states.empty else pd.NaT
        lead_days = int((event_date - first_warning).days) if pd.notna(first_warning) else None
        false_states = false_positive_window[state_col].dropna()
        false_positive_rate = float(false_states.isin(actionable_states).mean()) if not false_states.empty else 0.0
        event_states = signals.loc[event_date : event_date + pd.Timedelta(days=event_confirmation_days), state_col].dropna()
        event_state = max_state(event_states)
        event_action = action_tier(pd.Series([event_state])).iloc[0]
        rows.append(
            {
                "case": case.name,
                "indicator": name,
                "event_date": event_date.date().isoformat(),
                "first_state_warning": first_warning.date().isoformat() if pd.notna(first_warning) else None,
                "state_lead_days": lead_days,
                "state_false_positive_rate": false_positive_rate,
                "event_state": event_state,
                "event_action": event_action,
            }
        )
    return pd.DataFrame.from_records(rows)


def _event_observation_index(series: pd.Series, event_date: pd.Timestamp) -> pd.Timestamp | None:
    if series.empty:
        return None
    future = series.loc[event_date:]
    if not future.empty:
        return future.index[0]
    past = series.loc[:event_date]
    if not past.empty:
        return past.index[-1]
    return None


def run_historical_replay(
    raw: pd.DataFrame | None = None,
    cases: tuple[HistoricalCase, ...] = DEFAULT_CASES,
    threshold: float = 1.5,
    robust: bool = False,
    risk_policy: RiskPolicy = DEFAULT_RISK_POLICY,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = raw if raw is not None else fetch_default_fred_frame()
    signal_frames: list[pd.DataFrame] = []
    metric_frames: list[pd.DataFrame] = []
    state_metric_frames: list[pd.DataFrame] = []
    for case in cases:
        weekly = weekly_frame(frame, case.start, case.end)
        signals = build_structural_signals(weekly, robust=robust, risk_policy=risk_policy)
        signals = signals.copy()
        signals.insert(0, "case", case.name)
        signals.insert(1, "date", signals.index.date.astype(str))
        signal_frames.append(signals.reset_index(drop=True))
        indexed = signals.set_index(pd.to_datetime(signals["date"])).drop(columns=["case", "date"])
        metric_frames.append(backtest_warning_metrics(indexed, case, threshold=threshold))
        state_metric_frames.append(backtest_state_metrics(indexed, case))
    return (
        pd.concat(metric_frames, ignore_index=True),
        pd.concat(signal_frames, ignore_index=True),
        pd.concat(state_metric_frames, ignore_index=True),
    )
