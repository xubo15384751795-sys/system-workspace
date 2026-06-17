#!/usr/bin/env python3
"""Reconstruction data-availability spike.

Maps the 8 observable-state detectors (Sprint C of the Utility-First
reconstruction) to the series the harvester ACTUALLY ships, and emits a
go/no-go matrix. Run before building any detector, so we don't scaffold on a
missing data foundation.

Output:
    Output/reconstruction/DATA_AVAILABILITY_MATRIX.md
    Output/reconstruction/data_availability_matrix.csv
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
OUT = ROOT / "Output" / "reconstruction"

# Detector -> required series (real harvester series_ids). "optional" series do
# not gate the verdict; "core" series do.
DETECTORS: dict[str, dict] = {
    "vol_compression_stress": {
        "core": ["FRED:VIXCLS", "CBOE:VVIX", "CBOE:MOVE"],
        "optional": ["CBOE:SKEW", "DERIVED:VIX3M_VIX_SLOPE", "CBOE:SPX"],
    },
    "credit_widening_repair": {
        # OAS spreads exist but only from 2023; DBAA/DAAA + CP spread give long history.
        "core": ["DERIVED:CP_TBILL_SPREAD", "FRED:DBAA", "FRED:DAAA"],
        "optional": ["FRED:BAMLH0A0HYM2", "FRED:BAMLC0A0CM", "FRED:DCPF3M"],
    },
    "liquidity_drain_support": {
        "core": ["FRED:RRPONTSYD", "FRED:WTREGEN", "FRED:WRESBAL", "DERIVED:CP_TBILL_SPREAD"],
        "optional": ["DERIVED:SOFR_IORB_SPREAD", "FRED:WALCL"],
    },
    "dollar_pressure_relief": {
        "core": ["FRED:DTWEXBGS"],
        "optional": [],  # no EM FX, no DXY proper
    },
    "rates_shock_duration_relief": {
        "core": ["FRED:T10Y2Y", "FRED:DGS3MO", "FRED:DFF"],
        "optional": ["FRED:T10YIE", "FRED:T5YIE", "CBOE:MOVE"],
    },
    "cross_asset_repricing": {
        # Needs ETF price ratios (SPY/TLT, HYG/TLT, SLV/GLD) — none in panel.
        "core": ["ETF:SPY", "ETF:TLT", "ETF:HYG", "ETF:GLD", "ETF:SLV"],
        "optional": [],
    },
    "balance_sheet_support_stress": {
        "core": ["FRED:WALCL", "H41:primary_credit", "H41:discount_window", "FRED:WRESBAL"],
        "optional": ["H41:btfp", "FRED:RRPONTSYD", "FRED:WTREGEN"],
    },
    "risk_appetite_recovery_breakdown": {
        # Needs equity ETFs / sector ratios / breadth — none in panel.
        "core": ["ETF:QQQ", "ETF:IWM", "ETF:XLF", "ETF:KRE"],
        "optional": ["CBOE:SPX"],
    },
}

# Ready-made financial-stress indices available for cross-checking (long history).
STRESS_INDICES = ["FRED:NFCI", "FRED:NFCILEVERAGE", "FRED:NFCICREDIT",
                  "FRED:STLFSI4", "CISS", "OFR_FSI"]

RECENT_CUTOFF = pd.Timestamp("2026-05-01")  # core series must reach at least here


def load_coverage() -> pd.DataFrame:
    df = pd.read_parquet(PANEL)
    df["date"] = pd.to_datetime(df["date"])
    g = df.groupby("series_id").agg(
        rows=("value", "count"),
        start=("date", "min"),
        end=("date", "max"),
        freq=("frequency", lambda s: s.dropna().iloc[0] if s.notna().any() else "?"),
    )
    return g


def series_status(sid: str, cov: pd.DataFrame) -> dict:
    if sid not in cov.index:
        return {"present": False, "fresh": False, "start": None, "end": None,
                "freq": None, "rows": 0}
    r = cov.loc[sid]
    return {
        "present": True,
        "fresh": pd.Timestamp(r["end"]) >= RECENT_CUTOFF,
        "start": pd.Timestamp(r["start"]).date().isoformat(),
        "end": pd.Timestamp(r["end"]).date().isoformat(),
        "freq": r["freq"],
        "rows": int(r["rows"]),
    }


def verdict_for(core_ok: int, core_total: int, opt_ok: int) -> str:
    if core_ok == 0:
        return "NO_GO"
    if core_ok < core_total:
        return "AMBER"
    if opt_ok == 0 and core_total <= 1:
        return "AMBER"  # thin: single core series, no corroboration
    return "GO"


def main() -> None:
    cov = load_coverage()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    verdicts = {}

    for det, spec in DETECTORS.items():
        core = spec["core"]
        opt = spec["optional"]
        core_states = {s: series_status(s, cov) for s in core}
        opt_states = {s: series_status(s, cov) for s in opt}
        core_ok = sum(1 for s in core_states.values() if s["present"])
        opt_ok = sum(1 for s in opt_states.values() if s["present"])
        v = verdict_for(core_ok, len(core), opt_ok)
        verdicts[det] = v
        missing_core = [s for s, st in core_states.items() if not st["present"]]
        for s, st in {**core_states, **opt_states}.items():
            rows.append({
                "detector": det,
                "series_id": s,
                "tier": "core" if s in core else "optional",
                "present": st["present"],
                "fresh": st["fresh"],
                "freq": st["freq"],
                "start": st["start"],
                "end": st["end"],
                "rows": st["rows"],
            })
        rows.append({"detector": det, "series_id": "__VERDICT__", "tier": "",
                     "present": v, "fresh": "", "freq": "", "start": "",
                     "end": f"missing_core={missing_core}", "rows": ""})

    matrix = pd.DataFrame(rows)
    csv_path = OUT / "data_availability_matrix.csv"
    matrix.to_csv(csv_path, index=False)

    go = [d for d, v in verdicts.items() if v == "GO"]
    amber = [d for d, v in verdicts.items() if v == "AMBER"]
    nogo = [d for d, v in verdicts.items() if v == "NO_GO"]

    lines = [
        f"# Reconstruction Data-Availability Matrix — {datetime.now(UTC).date()}",
        "",
        f"Panel: `{PANEL.relative_to(ROOT)}` ({len(cov)} series).",
        "",
        f"- **GO ({len(go)}):** {', '.join(go) or '—'}",
        f"- **AMBER ({len(amber)}):** {', '.join(amber) or '—'}",
        f"- **NO-GO ({len(nogo)}):** {', '.join(nogo) or '—'}",
        "",
        "## Per-detector verdict",
        "",
        "| Detector | Verdict | Core present | Missing core |",
        "|---|---|---|---|",
    ]
    for det, spec in DETECTORS.items():
        core = spec["core"]
        present = [s for s in core if s in cov.index]
        missing = [s for s in core if s not in cov.index]
        lines.append(
            f"| {det} | {verdicts[det]} | {len(present)}/{len(core)} | "
            f"{', '.join(missing) or '—'} |"
        )

    lines += [
        "",
        "## Stress-index cross-checks (long history, all present)",
        "",
        "| Series | Present | Range |",
        "|---|---|---|",
    ]
    for s in STRESS_INDICES:
        st = series_status(s, cov)
        rng = f"{st['start']} → {st['end']}" if st["present"] else "—"
        lines.append(f"| {s} | {st['present']} | {rng} |")

    md_path = OUT / "DATA_AVAILABILITY_MATRIX.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"GO={go}")
    print(f"AMBER={amber}")
    print(f"NO_GO={nogo}")
    print(f"matrix: {csv_path}")
    print(f"report: {md_path}")


if __name__ == "__main__":
    main()
