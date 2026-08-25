#!/usr/bin/env python3
"""Build neutral macro-pressure gauges from an admitted Harvester panel.

This producer is intentionally independent of ``packages/framework`` and the
archived Deformation v1 claim set.  ``M`` and ``D`` appear only as temporary
compatibility keys for downstream consumers; their product meanings are
funding-mismatch pressure and market-constraint pressure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts._artifact_provenance import build_provenance
from scripts._runtime_io import ROOT, current_dir, write_json
from system_runtime.canonical_ids import (
    build_chain,
    build_claim,
    build_evidence,
    build_measurement,
    build_observation,
    lineage_ids,
)

DEFAULT_PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
MECHANISM_CARDS = ROOT / "docs" / "measurements" / "macro_pressure_mechanism_cards.md"

GAUGES: dict[str, dict[str, Any]] = {
    "M": {
        "product_name": "funding_mismatch_pressure",
        "display_name": "Funding mismatch pressure",
        "series": (
            "DERIVED:CP_TBILL_SPREAD",
            "DERIVED:SOFR_IORB_SPREAD",
            "FRED:NFCICREDIT",
        ),
    },
    "D": {
        "product_name": "market_constraint_pressure",
        "display_name": "Market constraint pressure",
        "series": (
            "FRED:NFCIRISK",
            "CBOE:MOVE",
            "DERIVED:SPX_ROLL_SPREAD",
        ),
    },
}


def _series(panel: pd.DataFrame, series_id: str) -> pd.Series:
    rows = panel.loc[panel["series_id"] == series_id, ["date", "value"]].copy()
    if rows.empty:
        return pd.Series(dtype=float, name=series_id)
    rows["date"] = pd.to_datetime(rows["date"], utc=True).dt.tz_convert(None)
    rows["value"] = pd.to_numeric(rows["value"], errors="coerce")
    return (
        rows.dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")["value"]
        .rename(series_id)
    )


def _causal_zscore(series: pd.Series, window: int = 756, min_periods: int = 126) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std().replace(0.0, np.nan)
    return ((series - mean) / std).clip(-4.0, 4.0)


def build_pressure_history(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    panel_dates = pd.to_datetime(panel["date"], utc=True, errors="coerce").dt.tz_convert(None).dropna()
    if panel_dates.empty:
        raise ValueError("neutral pressure panel has no usable dates")
    # Build every gauge on one shared business-day calendar.  Without this
    # reindex, ``ffill(limit=5)`` can only carry a component to dates already
    # present in that gauge, so a daily D observation can make a weekly M
    # observation look unavailable even though it is within the declared
    # carry-forward window.
    shared_calendar = pd.date_range(
        panel_dates.min().normalize(),
        panel_dates.max().normalize(),
        freq="B",
    )
    components: dict[str, pd.Series] = {}
    metadata: dict[str, Any] = {}
    for key, spec in GAUGES.items():
        gauge_components: list[pd.Series] = []
        component_meta: list[dict[str, Any]] = []
        for series_id in spec["series"]:
            raw = _series(panel, series_id)
            zscore = _causal_zscore(raw)
            components[f"{key}:{series_id}"] = zscore
            usable = zscore.dropna()
            component_meta.append(
                {
                    "series_id": series_id,
                    "raw_rows": int(raw.notna().sum()),
                    "usable_rows": int(usable.shape[0]),
                    "last_observation": str(usable.index[-1].date()) if not usable.empty else None,
                    "status": "usable" if not usable.empty else "missing_or_short_history",
                }
            )
            if not usable.empty:
                gauge_components.append(zscore)
        if gauge_components:
            # Align mixed daily/weekly evidence without looking forward. Five
            # business days is the maximum carry window; longer gaps remain
            # visibly unavailable and lower the claim ceiling.
            aligned = (
                pd.concat(gauge_components, axis=1)
                .sort_index()
                .reindex(shared_calendar)
                .ffill(limit=5)
            )
            gauge = aligned.mean(axis=1, skipna=True)
            minimum = 2 if len(gauge_components) >= 2 else 1
            gauge = gauge.where(aligned.notna().sum(axis=1) >= minimum)
        else:
            gauge = pd.Series(dtype=float)
        components[key] = gauge.rename(key)
        metadata[key] = {
            "product_name": spec["product_name"],
            "display_name": spec["display_name"],
            "components": component_meta,
            "required_usable_components": 2,
        }

    history = pd.concat({"M": components["M"], "D": components["D"]}, axis=1).sort_index()
    history.index.name = "date"
    return history, metadata


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 4) if np.isfinite(number) else None


def _state(m_value: float | None, d_value: float | None) -> str:
    values = [value for value in (m_value, d_value) if value is not None]
    if len(values) < 2:
        return "PRESSURE_READOUT_UNAVAILABLE"
    average = sum(values) / len(values)
    if average >= 1.0:
        return "BROAD_PRESSURE_HIGH"
    if average >= 0.35:
        return "PRESSURE_BUILDING"
    if average <= -0.35:
        return "PRESSURE_EASING"
    return "PRESSURE_BALANCED"


def _release_id() -> str:
    catalog = ROOT / "Data" / "harvester" / "exports" / "latest" / "catalog.json"
    if not catalog.exists():
        return "unknown"
    try:
        return str(json.loads(catalog.read_text(encoding="utf-8")).get("release_id", "unknown"))
    except (OSError, json.JSONDecodeError):
        return "unknown"


def _file_sha256(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def build_snapshot(panel_path: Path, history_path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    panel = pd.read_parquet(panel_path)
    required = {"date", "series_id", "value"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"benchmark panel missing columns: {sorted(missing)}")
    history, metadata = build_pressure_history(panel)
    usable = history.dropna(how="all")
    if usable.empty:
        raise ValueError("neutral pressure gauges have no usable observations")

    last = usable.iloc[-1]
    m_value = _finite(last.get("M"))
    d_value = _finite(last.get("D"))
    velocity = history.diff(20).iloc[-1] if len(history) > 20 else pd.Series(dtype=float)
    velocity_20d = {"M": _finite(velocity.get("M")), "D": _finite(velocity.get("D"))}
    n_deteriorating = sum(1 for value in velocity_20d.values() if value is not None and value > 0.2)
    state = _state(m_value, d_value)
    as_of = usable.index[-1].to_pydatetime().replace(tzinfo=UTC).isoformat()
    run_id = os.environ.get("ZCODE_BUNDLE_RUN_ID") or f"neutral_pressure_{as_of[:10]}"
    both_live = m_value is not None and d_value is not None
    quality = "FULL_WITH_WARNINGS" if both_live else "PARTIAL"
    overall = "ACTIVE_PARTIAL" if both_live else "DEGRADED_PARTIAL"

    degraded_reasons = [] if both_live else ["one_or_more_neutral_gauges_unavailable"]
    provenance = build_provenance(
        producer_step="neutral_pressure_measurement",
        source_release_id=_release_id(),
        as_of_date=as_of[:10],
        input_paths=[panel_path, MECHANISM_CARDS],
        validation_verdict="pass" if both_live else "degraded",
        claim_ceiling="bounded_neutral_measurement",
        degraded_reasons=degraded_reasons,
    )
    # Standalone reproductions do not receive the bundle environment variable;
    # they still need a non-empty identity and must agree with the payload.
    provenance["run_id"] = run_id

    # The legacy snapshot remains intact, but its new canonical envelope gives
    # every downstream consumer one deterministic observation -> measurement
    # -> evidence -> claim lineage.  The panel snapshot hash makes retries
    # idempotent while still producing a new observation when the input itself
    # is revised.
    panel_snapshot_sha256 = _file_sha256(panel_path)
    canonical_observation = build_observation(
        canonical_series_id="SYSTEM:NEUTRAL_PRESSURE_PANEL",
        observed_at=as_of,
        value={"M": m_value, "D": d_value},
        source_id="harvester:benchmark_panel",
        unit="bounded_pressure_gauge",
        source_snapshot_sha256=panel_snapshot_sha256,
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
        },
    )
    canonical_measurement = build_measurement(
        observation_ids=[canonical_observation["observation_id"]],
        measurement_definition="macro_pressure_measurement",
        value={"M": m_value, "D": d_value},
        unit="bounded_pressure_gauge",
        status="AVAILABLE" if both_live else "MISSING",
        derivation="PROXY_DERIVED",
        confidence=0.7 if both_live else 0.35,
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
            "method": "causal_zscore_and_component_mean",
        },
    )
    canonical_evidence = build_evidence(
        measurement_ids=[canonical_measurement["measurement_id"]],
        evidence_role="PRIMARY",
        source_id="harvester:benchmark_panel",
        release_id=_release_id() or None,
        source_snapshot_sha256=panel_snapshot_sha256,
        status="AVAILABLE" if panel_snapshot_sha256 else "UNKNOWN",
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
            "source_url": str(panel_path),
        },
    )
    canonical_claim = build_claim(
        claim_text=f"Neutral macro-pressure state is {state}.",
        subject="neutral_macro_pressure",
        predicate="has_state",
        evidence_ids=[canonical_evidence["evidence_id"]],
        status="WATCH",
        confidence=0.7 if both_live else 0.35,
        provenance={
            **provenance,
            "captured_at": provenance.get("generated_at", as_of),
            "producer": "neutral_pressure_measurement",
            "statement_kind": "bounded_neutral_measurement",
            "claim_ceiling": "bounded_neutral_measurement",
            "promotion_allowed": False,
        },
    )
    canonical_chain = build_chain(
        observation=canonical_observation,
        measurement=canonical_measurement,
        evidence=canonical_evidence,
        claim=canonical_claim,
    )

    snapshot: dict[str, Any] = {
        "schema_version": "neutral_pressure.snapshot.v1",
        "measurement_id": "macro_pressure_measurement",
        "framework_id": "macro_pressure_measurement",
        "producer": "neutral_pressure_measurement",
        "run_id": run_id,
        "as_of": as_of,
        "provenance": provenance,
        "canonical_chain": canonical_chain,
        "canonical_ids": lineage_ids(canonical_chain),
        "status": "active_partial" if both_live else "degraded_partial",
        "basic": {
            "overall": overall,
            "quality_status": quality,
            "main_pressure": state,
            "confidence": "bounded measurement only; no universal prediction authority",
            "summary": (
                f"Neutral macro-pressure state is {state}. Funding mismatch pressure={m_value}; "
                f"market constraint pressure={d_value}. This is a measurement dashboard, not a market theory."
            ),
            "primary_market_space": state,
            "daily_readout_policy": "Use neutral M/D compatibility gauges for bounded monitoring only.",
        },
        "advanced": {
            "primary_readout": {
                "state": state,
                "M_anchor_geometry": {
                    "value": m_value,
                    "compatibility_key": "M",
                    "product_name": "funding_mismatch_pressure",
                },
                "D_path_geometry": {
                    "value": d_value,
                    "compatibility_key": "D",
                    "product_name": "market_constraint_pressure",
                },
                "theory_authority": "none",
            },
            "sigma_vector": {
                "M": m_value,
                "D": d_value,
                "K": None,
                "X_agg": None,
                "channels_live": [key for key, value in (("M", m_value), ("D", d_value)) if value is not None],
                "channels_not_implemented": ["K", "X_agg"],
                "complete": False,
                "dominant_channel": "NONE",
                "cofire_count": 0,
                "velocity_20d": velocity_20d,
                "n_deteriorating": n_deteriorating,
                "semantic_warning": [
                    "M and D are compatibility keys for neutral gauges, not Deformation dimensions.",
                    "K and X are excluded from the operational product and remain research-only candidates.",
                ],
            },
            "channel_coverage": {
                "channels_live": [key for key, value in (("M", m_value), ("D", d_value)) if value is not None],
                "channels_not_implemented": ["K", "X_agg"],
                "total_canonical": 2,
                "coverage_ratio": f"{int(m_value is not None) + int(d_value is not None)}/2",
                "complete": both_live,
            },
            "channel_confidence": {
                key: {
                    "status": "live" if value is not None else "unavailable",
                    "confidence": "medium",
                    "proxy_quality": "LITERATURE_GROUNDED_REQUALIFICATION",
                    "readout_role": "neutral_measurement",
                    "product_name": GAUGES[key]["product_name"],
                }
                for key, value in (("M", m_value), ("D", d_value))
            },
            "measurement_eligibility": {
                "M": {"readout_role": "neutral_measurement", "theory_authority": "none"},
                "D": {"readout_role": "neutral_measurement", "theory_authority": "none"},
                "K": {"readout_role": "research_only", "operational_wiring": "denied"},
                "X_agg": {"readout_role": "research_only", "operational_wiring": "denied"},
            },
            "quality_status": quality,
            "measurement_blind_spot": not both_live,
            "coverage_ratio": f"{int(m_value is not None) + int(d_value is not None)}/2",
            "harvester_release": _release_id(),
            "semantic_warnings": ["Archived Deformation v1 claims have no authority over this output."],
            "component_metadata": metadata,
        },
        "artifacts": {
            "pressure_history": str(history_path),
            "mechanism_cards": str(MECHANISM_CARDS),
        },
        "evidence_links": [str(panel_path), str(MECHANISM_CARDS)],
        "next_actions": [
            "Continue common-sample validation of the neutral gauges against public baselines.",
            "Keep velocity-gate requalification in Strategy Lab until input-independence tests pass.",
        ],
        "legacy_compatibility": {
            "framework_output_filename": True,
            "deformation_v1_theory_authority": False,
            "falsified_claim_set": "deformation_v1_four_channel_universal_predictor",
        },
    }
    return snapshot, history


def compatibility_framework_output(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = dict(snapshot)
    payload["schema_version"] = "workbench.framework_output.v3"
    payload["framework_version"] = "1.0.0"
    payload.pop("measurement_id", None)
    payload.pop("producer", None)
    payload.pop("legacy_compatibility", None)
    return payload


def write_snapshot_files(
    snapshot: dict[str, Any],
    history: pd.DataFrame,
    *,
    output_dir: Path,
    history_path: Path,
) -> tuple[Path, Path, Path]:
    """Write a snapshot using an explicit output boundary.

    ``build_snapshot`` remains the calculation authority.  This helper is the
    migration seam used by the Dagster shadow path; it never resolves
    ``current_dir()`` or the legacy run directory itself.
    """
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history.to_parquet(history_path)
    snapshot_path = output_dir / "neutral_pressure_snapshot.json"
    framework_path = output_dir / "framework_output.json"
    write_json(snapshot_path, snapshot)
    write_json(framework_path, compatibility_framework_output(snapshot))
    return snapshot_path, framework_path, history_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build neutral macro-pressure gauges")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--current-output", type=Path, default=None)
    parser.add_argument("--history-output", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    run_id = os.environ.get("ZCODE_BUNDLE_RUN_ID") or datetime.now(UTC).strftime("neutral_%Y%m%dT%H%M%SZ")
    history_path = args.history_output or ROOT / "Output" / "runs" / run_id / "neutral_pressure" / "pressure_history.parquet"
    output_dir = args.current_output or current_dir()
    snapshot, history = build_snapshot(args.panel, history_path)
    write_snapshot_files(
        snapshot,
        history,
        output_dir=output_dir,
        history_path=history_path,
    )
    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(f"Neutral pressure snapshot: {output_dir / 'neutral_pressure_snapshot.json'}")


if __name__ == "__main__":
    main()
