"""OBS-4: LDI-focused ProviderIntegrity-style panel as ObservationIntegrity (diagnostic-only)."""

from __future__ import annotations

import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.dynamic.integrity_series_metrics import compute_forward_fill_ratio
from src.dynamic.observation_integrity import ObservationIntegrity, ProviderIntegrityCheck
from src.dynamic.registry import get_temporal_frame
from src.dynamic.static_source_risk import detect_static_source_risk

DEMO_DISCLAIMER = (
    "Diagnostic-only observation integrity panel; not connected to final scoring, provider "
    "pipelines, or Snapshot output. Do not use for execution or risk decisions."
)

# FRED graph CSV ids — loaded only from local cache under the project (no network in this builder).
_UK_LONG_END_CANDIDATE = "IRLTLT01GBM156N"  # OECD: UK central govt bonds, 10y+ (monthly)
_US_10Y_CURVE_PROXY = "DGS10"  # US Treasury 10Y (daily) as curve proxy when UK10Y cache absent


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fred_cache_dir() -> Path:
    return _project_root() / "data" / "raw" / "fred"


def _read_fred_graph_csv_file(series_id: str, path: Path) -> pd.Series | None:
    if not path.is_file():
        return None
    try:
        frame = pd.read_csv(StringIO(path.read_text(encoding="utf-8")))
    except OSError:
        return None
    if "observation_date" not in frame.columns or series_id not in frame.columns:
        return None
    series = pd.to_numeric(frame[series_id], errors="coerce")
    series.index = pd.to_datetime(frame["observation_date"], errors="coerce")
    series = series[~series.index.isna()].dropna().sort_index()
    series.name = series_id
    return series


def _try_load_cached_fred_series(series_id: str) -> tuple[pd.Series | None, str]:
    """Return (series, provenance_label). Read-only; no HTTP."""
    path = _fred_cache_dir() / f"{series_id}.csv"
    s = _read_fred_graph_csv_file(series_id, path)
    if s is not None and not s.empty:
        return s, f"real_fred_local_cache:{series_id}"
    return None, "missing_cache"


def _synthetic_ldi_yield_daily(logical_key: str, seed: int) -> pd.Series:
    """Documented business-day synthetic series for LDI 2022 window (percent yield style)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-08-15", "2022-11-20")
    walk = np.cumsum(rng.normal(0.0, 0.03, size=len(idx)))
    base = 3.2 if "long" in logical_key else 3.0
    shock_bump = np.zeros(len(idx))
    shock_mask = np.asarray((idx >= "2022-09-23") & (idx <= "2022-09-28"), dtype=bool)
    shock_bump[shock_mask] = rng.uniform(0.8, 1.4, size=int(shock_mask.sum()))
    intervention_flat = np.asarray((idx >= "2022-09-28") & (idx <= "2022-10-10"), dtype=bool)
    vals = base + walk * 0.02 + shock_bump
    n_iflat = int(intervention_flat.sum())
    if n_iflat:
        vals[intervention_flat] = vals[intervention_flat] * 0.98 + rng.normal(0, 0.01, size=n_iflat)
    return pd.Series(vals, index=idx, name=logical_key)


def _phase_by_name(frame: Any, name: str) -> tuple[str, str] | None:
    for p in frame.phases:
        if p.name == name:
            return (p.start, p.end)
    return None


def _worst_overall_status(checks: list[ProviderIntegrityCheck]) -> str:
    rank = {"fail": 5, "warn": 4, "watch": 3, "unknown": 2, "pass": 1}
    worst = max(checks, key=lambda c: rank.get(c.status, 0))
    m = {"fail": "failed", "warn": "weak", "watch": "medium", "pass": "strong", "unknown": "unknown"}
    return m.get(worst.status, "unknown")


def _aggregate_static_risk_scalar(checks: list[ProviderIntegrityCheck]) -> float | None:
    scores = [c.staleness_score for c in checks if c.staleness_score is not None]
    if not scores:
        return None
    return float(max(scores))


def _build_ldi_2022_observation_integrity(
    *,
    force_synthetic_demo: bool,
) -> tuple[ObservationIntegrity, dict[str, str], list[str]]:
    case_id = "ldi_2022"
    frame = get_temporal_frame(case_id)
    required_resolution = frame.required_resolution
    shock = _phase_by_name(frame, "shock")
    intervention = _phase_by_name(frame, "intervention")
    if shock is None or intervention is None:
        raise ValueError("ldi_2022 TemporalFrame must define shock and intervention phases")

    provenance: dict[str, str] = {}
    synthetic_markers: list[str] = []

    if not force_synthetic_demo:
        uk_long, p_long = _try_load_cached_fred_series(_UK_LONG_END_CANDIDATE)
        provenance["uk_long_end_gilt"] = p_long
        if uk_long is None:
            uk_long = _synthetic_ldi_yield_daily("uk_long_end_gilt", seed=41)
            provenance["uk_long_end_gilt"] = "synthetic_demo_business_daily_yield_shape"
            synthetic_markers.append("uk_long_end_gilt:entire_series_synthetic_demo")
    else:
        uk_long = _synthetic_ldi_yield_daily("uk_long_end_gilt", seed=41)
        provenance["uk_long_end_gilt"] = "synthetic_demo_business_daily_yield_shape"
        synthetic_markers.append("uk_long_end_gilt:entire_series_synthetic_demo")

    uk10_fallback_substitute = False
    if not force_synthetic_demo:
        uk10, p10 = _try_load_cached_fred_series(_US_10Y_CURVE_PROXY)
        provenance["uk_10y_curve_proxy"] = p10
        if uk10 is None:
            uk10 = _synthetic_ldi_yield_daily("uk_10y_curve_proxy", seed=42)
            provenance["uk_10y_curve_proxy"] = "synthetic_demo_business_daily_curve_proxy"
            synthetic_markers.append("uk_10y_curve_proxy:entire_series_synthetic_demo")
        else:
            uk10_fallback_substitute = True
            provenance["uk_10y_curve_proxy_note"] = (
                "Real cached DGS10 (US 10Y Treasury) used as global curve proxy; not a UK gilt 10Y series."
            )
    else:
        uk10 = _synthetic_ldi_yield_daily("uk_10y_curve_proxy", seed=42)
        provenance["uk_10y_curve_proxy"] = "synthetic_demo_business_daily_curve_proxy"
        synthetic_markers.append("uk_10y_curve_proxy:entire_series_synthetic_demo")

    freq_long = "monthly" if provenance["uk_long_end_gilt"].startswith("real_fred") else "daily"
    freq_10y = "daily"

    series_specs: list[dict[str, Any]] = [
        {
            "logical_series": "uk_long_end_gilt",
            "series": uk_long,
            "provider": "FRED" if provenance["uk_long_end_gilt"].startswith("real_fred") else None,
            "frequency": freq_long,
            "fallback_used": False,
            "mock_used": False,
            "ffill_metadata": None,
        },
        {
            "logical_series": "uk_10y_curve_proxy",
            "series": uk10,
            "provider": "FRED" if provenance["uk_10y_curve_proxy"].startswith("real_fred") else None,
            "frequency": freq_10y,
            "fallback_used": uk10_fallback_substitute,
            "mock_used": False,
            "ffill_metadata": {"forward_fill_ratio": 0.0},
        },
    ]

    checks: list[ProviderIntegrityCheck] = []
    for spec in series_specs:
        s = spec["series"]
        assert isinstance(s, pd.Series)
        for window_name, win in (("shock", shock), ("intervention", intervention)):
            logical = f"{spec['logical_series']}__{window_name}"
            chk = detect_static_source_risk(
                s,
                event_window=win,
                high_stress=True,
                logical_series=logical,
                provider=spec["provider"],
                frequency=spec["frequency"],
                required_resolution=required_resolution,
                fallback_used=spec["fallback_used"],
                mock_used=spec["mock_used"],
            )
            ffill = compute_forward_fill_ratio(s, spec["ffill_metadata"])
            prov_detail = provenance.get(spec["logical_series"], "")
            chk = replace(
                chk,
                forward_fill_ratio=ffill,
                provider_disagreement=None,
                interpretation=(
                    f"{chk.interpretation} | LDI 2022 {window_name} window; "
                    f"static-source sensitivity with high_stress=True. "
                    f"Series provenance: {prov_detail}."
                ),
            )
            checks.append(chk)

    overall = _worst_overall_status(checks)
    static_scalar = _aggregate_static_risk_scalar(checks)

    syn_note = (
        "Synthetic/demo substitution was used where noted in data_provenance; see synthetic_or_demo_fields."
        if synthetic_markers
        else "No full-series synthetic substitution was required (local caches supplied all inputs)."
    )
    summary = (
        f"LDI 2022 provider integrity panel ({case_id}): shock and intervention windows from "
        f"TemporalFrame; high-stress static-source checks per series. {syn_note} "
        f"data_provenance={json.dumps(provenance, sort_keys=True)}."
    )

    obs = ObservationIntegrity(
        case_id=case_id,
        overall_status=overall,
        checks=checks,
        static_source_risk=static_scalar,
        provider_disagreement_available=False,
        summary=summary,
        diagnostic_only=True,
    )
    return obs, provenance, synthetic_markers


def build_provider_integrity_panel(
    case_id: str = "ldi_2022",
    *,
    force_synthetic_demo: bool = False,
) -> ObservationIntegrity:
    """Build an LDI-focused :class:`ObservationIntegrity` panel (diagnostic-only).

    Loads UK long-end / curve-proxy series from local FRED graph CSV caches when present
    (``data/raw/fred/<id>.csv``). Otherwise uses documented synthetic business-day series.
    """
    if case_id != "ldi_2022":
        raise ValueError(f"OBS-4 demo currently supports case_id='ldi_2022' only; got {case_id!r}")
    obs, _, _ = _build_ldi_2022_observation_integrity(force_synthetic_demo=force_synthetic_demo)
    return obs


def build_ldi_2022_provider_integrity_panel_json_dict(
    *,
    force_synthetic_demo: bool = False,
) -> dict[str, object]:
    obs, provenance, synthetic_markers = _build_ldi_2022_observation_integrity(
        force_synthetic_demo=force_synthetic_demo
    )
    temporal = get_temporal_frame("ldi_2022").to_serializable_dict()
    return {
        "ldi_provider_integrity_panel_version": "obs-4-demo",
        "diagnostic_only_disclaimer": DEMO_DISCLAIMER,
        "data_provenance": provenance,
        "synthetic_or_demo_fields": synthetic_markers,
        "temporal_frame": temporal,
        "observation_integrity": obs.to_serializable_dict(),
    }


def default_ldi_provider_integrity_output_path() -> Path:
    return _project_root() / "outputs" / "dynamic_demo" / "ldi_2022_provider_integrity_panel.json"


def write_ldi_2022_provider_integrity_panel(
    path: Path | None = None,
    *,
    force_synthetic_demo: bool = False,
) -> Path:
    target = path or default_ldi_provider_integrity_output_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_ldi_2022_provider_integrity_panel_json_dict(force_synthetic_demo=force_synthetic_demo)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target
