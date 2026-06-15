#!/usr/bin/env python3
"""Primitive-coordinate readiness matrix.

Maps the 6 primitive coordinates z_t = (S, A, L, V, P, tau) — the proposed market-
space coordinate layer beneath M/D/K/X — to the evidence the harvester actually
ships. Answers: which coordinate axes are real vs. aspirational, BEFORE building a
6-panel measurement layer.

A family is "covered" if >=1 backing series is present, or it is derivable from
panel metadata (frequency / vintage_date columns) — marked META.

Output:
    Output/reconstruction/PRIMITIVE_READINESS_MATRIX.md
    Output/reconstruction/primitive_readiness_matrix.csv
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "Data" / "harvester" / "exports" / "latest" / "data" / "benchmark_panel.parquet"
OUT = ROOT / "Output" / "reconstruction"

META = "__PANEL_METADATA__"  # derivable from frequency/vintage_date columns

# primitive -> evidence_family -> backing series_ids (real) or META.
PRIMITIVES: dict[str, dict[str, list[str]]] = {
    "S_strategic_actor": {
        "actor_concentration": [],
        "dealer_positioning": [],
        "flow_concentration": [],
        "breadth": [],
    },
    "A_anchor": {
        "rates_anchor": ["FRED:T10Y2Y", "FRED:DGS3MO", "FRED:DFF"],
        "policy_anchor": ["FRED:SOFR", "FRED:IORB", "DERIVED:SOFR_IORB_SPREAD"],
        "inflation_anchor": ["FRED:T10YIE", "FRED:T5YIE"],
        "dollar_anchor": ["FRED:DTWEXBGS"],
        "credit_anchor": ["FRED:DBAA", "FRED:DAAA", "DERIVED:CP_TBILL_SPREAD"],
    },
    "L_liquidation_path": {
        "funding_access": ["DERIVED:SOFR_IORB_SPREAD", "FRED:RRPONTSYD",
                            "DERIVED:CP_TBILL_SPREAD", "FRED:DCPF3M"],
        "market_depth": [],          # bid-ask / Amihud / ETF NAV gap — absent
        "hedge_breadth": [],         # options OI breadth — absent
        "dealer_absorption": [],     # primary dealer positions — absent
    },
    "V_verifiability": {
        "filing_pulse": ["SEC:0000072971"],
        "obs_exposure": ["SEC:OBS_DERIV_TO_ASSETS"],
        "accounting_market_gap": [],  # HTM losses / bank equity — absent
        "stale_valuation": [],        # private valuation lag — absent
        "price_verifiability": [],    # ETF NAV gap — absent
    },
    "P_power_concentration": {
        "holdings_concentration": [],
        "dealer_inventory": [],
        "short_interest": [],
        "gamma_concentration": [],
        "sector_concentration": [],   # needs sector ETFs — absent
    },
    "tau_latency": {
        "frequency_latency": [META],                       # frequency column
        "reporting_lag": [META, "SEC:OBS_DERIV_TO_ASSETS"],  # vintage_date column
        "realization_lag": ["FRED:VIXCLS", "CBOE:SPX"],    # implied vs realized vol
        "maturity_lag": [],
        "policy_response_lag": [],
    },
}


def load_present() -> set[str]:
    df = pd.read_parquet(PANEL, columns=["series_id"])
    return set(df["series_id"].unique())


def family_covered(series: list[str], present: set[str]) -> tuple[bool, str]:
    backing = [s for s in series if s == META or s in present]
    if not backing:
        return False, "—"
    return True, ", ".join(backing)


def verdict(n_cov: int, n_total: int) -> str:
    if n_cov == 0:
        return "NO_GO"
    if n_cov == n_total:
        return "GO"
    return "PARTIAL"


def main() -> None:
    present = load_present()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    verdicts = {}

    for prim, families in PRIMITIVES.items():
        cov = 0
        for fam, series in families.items():
            ok, backing = family_covered(series, present)
            cov += int(ok)
            rows.append({"primitive": prim, "evidence_family": fam,
                         "covered": ok, "backing": backing})
        verdicts[prim] = verdict(cov, len(families))
        rows.append({"primitive": prim, "evidence_family": "__VERDICT__",
                     "covered": verdicts[prim],
                     "backing": f"{cov}/{len(families)} families"})

    pd.DataFrame(rows).to_csv(OUT / "primitive_readiness_matrix.csv", index=False)

    go = [p for p, v in verdicts.items() if v == "GO"]
    partial = [p for p, v in verdicts.items() if v == "PARTIAL"]
    nogo = [p for p, v in verdicts.items() if v == "NO_GO"]

    lines = [
        f"# Primitive-Coordinate Readiness Matrix — {datetime.now(UTC).date()}",
        "",
        f"Panel: `{PANEL.relative_to(ROOT)}`. META = derivable from frequency/vintage_date columns.",
        "",
        f"- **GO ({len(go)}):** {', '.join(go) or '—'}",
        f"- **PARTIAL ({len(partial)}):** {', '.join(partial) or '—'}",
        f"- **NO-GO ({len(nogo)}):** {', '.join(nogo) or '—'}",
        "",
        "## Per-coordinate readiness",
        "",
        "| Coordinate | Verdict | Families covered |",
        "|---|---|---|",
    ]
    for prim, families in PRIMITIVES.items():
        cov = sum(family_covered(s, present)[0] for s in families.values())
        lines.append(f"| {prim} | {verdicts[prim]} | {cov}/{len(families)} |")

    lines += ["", "## Missing evidence families (the procurement gaps)", ""]
    for prim, families in PRIMITIVES.items():
        missing = [f for f, s in families.items() if not family_covered(s, present)[0]]
        if missing:
            lines.append(f"- **{prim}:** {', '.join(missing)}")

    (OUT / "PRIMITIVE_READINESS_MATRIX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"GO={go}")
    print(f"PARTIAL={partial}")
    print(f"NO_GO={nogo}")
    print(f"report: {OUT / 'PRIMITIVE_READINESS_MATRIX.md'}")


if __name__ == "__main__":
    main()
