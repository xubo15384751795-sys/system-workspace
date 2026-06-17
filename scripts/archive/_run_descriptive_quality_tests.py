"""5-dimension descriptive-quality test harness.

Reads existing replay/diagnostic artefacts and grades them against the
description-quality framework (channel identification, differentiation,
self-calibration, lead-time, data integrity). Outputs a single scorecard
to stdout. No model rerun required.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/a1/System")
REPLAY = ROOT / "Output/sandbox/structural_replay_v2/results.json"
HUMAN_REVIEW = ROOT / "Output/sandbox/structural_replay_v2/human_review.md"
FRESHNESS = ROOT / "Output/current/freshness_manifest.json"
RUN_MANIFEST = ROOT / "Output/current/run_manifest.json"
REJECTION = ROOT / "Output/deformation_runs/2026-05-17_C005_MORPHOLOGY/diagnostics/rejection_flags.json"
RESIDUAL = ROOT / "Output/deformation_runs/2026-05-17_C005_MORPHOLOGY/diagnostics/residual_tests.json"

# Expected leading channel family per the user's framework + human_review.
# Families: M, D, K, X. X covers X_PRE and X_REALIZED.
EXPECTED = {
    "asian_1997":       ("X", "EM currency/credit contagion"),
    "ltcm_1998":        ("D", "Credit/liquidity unwind"),
    "dotcom_2000":      ("K", "Equity valuation, no credit damage"),
    "worldcom_2002":    ("D", "Credit accounting blow-up"),
    "gfc_2008":         ("D", "Credit depth collapse (canonical)"),
    "flash_crash_2010": ("K", "Pure technical vol event"),
    "euro_debt_2011":   ("K", "Rates vol / sovereign concerns"),
    "taper_2013":       ("K", "Rates vol only"),
    "china_2015":       ("X", "Cross-asset/FX contagion"),
    "brexit_2016":      ("K", "One-day vol shock"),
    "volmageddon_2018": ("K", "XIV collapse, no credit"),
    "repo_2019":        ("D", "Repo market seizure"),
    "covid_2020":       ("D", "Across-the-board liquidity freeze"),
    "ldi_2022":         ("M", "Rates/funding (gilt + pension)"),
    "svb_2023":         ("X", "Banking contagion (BTFP)"),
    "august_2024":      ("K", "Carry unwind, vol spike"),
}


def family(channel: str) -> str:
    if channel.startswith("X"):
        return "X"
    if channel.startswith("D"):
        return "D"
    return channel[:1]


def first_to_cross(event) -> str:
    """Channel that first crossed its threshold (most positive days_before_peak)."""
    path = event.get("observed_path") or []
    if not path:
        return "—"
    # filter to entries that triggered before peak (days_before_peak > 0 = before)
    pre_peak = [p for p in path if p["days_before_peak"] > 0]
    if not pre_peak:
        # fall back: earliest crossing (largest days_before_peak)
        return max(path, key=lambda p: p["days_before_peak"])["channel"]
    return max(pre_peak, key=lambda p: p["days_before_peak"])["channel"]


def channel_at_peak_leader(event) -> str:
    cap = event.get("channel_at_peak") or {}
    if not cap:
        return "—"
    return max(cap.items(), key=lambda kv: kv[1])[0]


def channel_window_max_leader(event) -> str:
    """Channel with the largest threshold-cross value over the event window."""
    path = event.get("observed_path") or []
    if not path:
        return "—"
    return max(path, key=lambda p: p["value"])["channel"]


def lead_days(event) -> int:
    """Days before peak when ANY structural channel first crossed threshold."""
    path = event.get("observed_path") or []
    pre = [p["days_before_peak"] for p in path if p["days_before_peak"] > 0]
    return max(pre) if pre else 0


def fmt(b: bool) -> str:
    return "PASS" if b else "FAIL"


def main():
    events = json.loads(REPLAY.read_text())
    events_by_id = {e["event_id"]: e for e in events}

    print("=" * 78)
    print(" 5-DIMENSION DESCRIPTIVE-QUALITY TEST  (run: 2026-05-18)")
    print(" Replay:", REPLAY.relative_to(ROOT))
    print(" Events:", len(events))
    print("=" * 78)

    # ---------------------------------------------------------------- D1
    print("\n--- D1  Channel identification consistency  ----------------------------")
    print(f"{'event':22s} {'expect':6s} | {'1st-cross':14s} {'win-max':14s} {'at-peak':14s} | verdict")
    d1_first = d1_winmax = d1_atpeak = 0
    for eid, (exp, _) in EXPECTED.items():
        e = events_by_id[eid]
        f = family(first_to_cross(e))
        w = family(channel_window_max_leader(e))
        p = family(channel_at_peak_leader(e))
        ok_any = exp in {f, w, p}
        d1_first += (f == exp)
        d1_winmax += (w == exp)
        d1_atpeak += (p == exp)
        mark = "OK" if ok_any else "MISS"
        print(f"{eid:22s} {exp:6s} | "
              f"{first_to_cross(e):14s} {channel_window_max_leader(e):14s} {channel_at_peak_leader(e):14s} | {mark}")
    n = len(EXPECTED)
    print(f"\nScoring  first-crosser:    {d1_first}/{n}")
    print(f"         window-max:       {d1_winmax}/{n}")
    print(f"         at-peak leader:   {d1_atpeak}/{n}")
    print(f"         any-of-three OK:  "
          f"{sum(1 for eid,(exp,_) in EXPECTED.items() if exp in {family(first_to_cross(events_by_id[eid])), family(channel_window_max_leader(events_by_id[eid])), family(channel_at_peak_leader(events_by_id[eid]))})}/{n}")
    print("Pass criterion = at least one definition matches.  "
          "(\"first-crosser\" is the most operationally meaningful: what the system would have said in real time.)")

    # ---------------------------------------------------------------- D2
    print("\n--- D2  Differentiation across same-baseline events  -------------------")
    print("Grouping by VIX_zscore bins; within each bin leading channels should differ.")
    bins = [("calm  (VIX<2)", lambda v: v < 2.0),
            ("med   (2-4)",   lambda v: 2.0 <= v < 4.0),
            ("severe(>=4)",   lambda v: v >= 4.0)]
    groups: dict[str, list] = defaultdict(list)
    for eid, e in events_by_id.items():
        vix = e.get("benchmark_context", {}).get("VIX_zscore", 0.0)
        nfci = e.get("benchmark_context", {}).get("NFCI_zscore", 0.0)
        for name, pred in bins:
            if pred(vix):
                groups[name].append((eid, vix, nfci, family(first_to_cross(e))))
                break
    pass_count = 0
    for name, _ in bins:
        members = groups.get(name, [])
        if len(members) < 2:
            print(f"  [{name}]  (only {len(members)} events — cannot test differentiation)")
            continue
        leads = {m[3] for m in members}
        ok = len(leads) >= 2
        pass_count += ok
        print(f"  [{name}]  members={len(members)}  distinct_leading_families={len(leads)}  → {fmt(ok)}")
        for eid, vix, nfci, lead in members:
            print(f"      {eid:22s}  VIX={vix:5.2f}  NFCI={nfci:5.2f}  lead={lead}")
    print(f"Bins with >=2 distinct leading channels: {pass_count} / {sum(1 for n,_ in bins if len(groups.get(n,[]))>=2)}")

    # Also test the canonical C005 trio (GFC vs COVID vs SVB), all severe.
    trio = ["gfc_2008", "covid_2020", "svb_2023"]
    fams = {eid: family(first_to_cross(events_by_id[eid])) for eid in trio}
    print(f"\n  C005 severe-trio test:  {fams}  → distinct: {fmt(len(set(fams.values())) == 3)}")

    # ---------------------------------------------------------------- D3
    print("\n--- D3  Self-calibration  ----------------------------------------------")
    rej = json.loads(REJECTION.read_text())
    res = json.loads(RESIDUAL.read_text())
    d3a = bool(rej)                                           # non-empty
    d3a_res = bool(res) and not all(v is None for v in res.values())
    d3b = rej.get("benchmark_dominance_K_vs_vol_jump_tail") is True
    d3c_count = sum(1 for v in res.values() if isinstance(v, (int, float)))
    print(f"  3a  rejection_flags non-empty:        {fmt(d3a)}   keys={len(rej)}")
    print(f"  3a  residual_tests non-empty:         {fmt(d3a_res)} keys={len(res)}")
    print(f"  3b  K_vs_vol_jump_tail dominance=True: {fmt(d3b)}  (known C005 shortfall)")
    print(f"  3c  residuals carry numeric values:    {d3c_count}/{len(res)}")
    print(f"      Sigma_resid_vs_aggregate_stress = {res.get('Sigma_resid_vs_aggregate_stress')}")
    print(f"      K_resid_vs_vol_jump_tail        = {res.get('K_resid_vs_vol_jump_tail')}  (large → K dominated)")
    print(f"      M_resid_vs_NFCI                 = {res.get('M_resid_vs_NFCI')}        (near 0 → M aligned w/ NFCI)")

    # ---------------------------------------------------------------- D4
    print("\n--- D4  Lead-time (>=30 days WATCH before peak)  -----------------------")
    print(f"{'event':22s}  lead_days   {'first-crosser':15s} verdict")
    d4_pass = d4_total = 0
    for eid in EXPECTED:
        e = events_by_id[eid]
        ld = lead_days(e)
        d4_total += 1
        ok = ld >= 30
        d4_pass += ok
        print(f"  {eid:22s}  {ld:5d}d      {first_to_cross(e):15s} {fmt(ok)}")
    print(f"\nLead-time pass rate (>=30d): {d4_pass}/{d4_total}")
    print("Known shortfall events (acceptable if documented): ldi_2022, repo_2019, flash_crash_2010")

    # ---------------------------------------------------------------- D5
    print("\n--- D5  Data integrity  ------------------------------------------------")
    fm = json.loads(FRESHNESS.read_text())
    rm = json.loads(RUN_MANIFEST.read_text())
    indicators = fm["indicators"]
    fresh = sum(1 for i in indicators if i["freshness_status"] == "fresh")
    missing = sum(1 for i in indicators if i["freshness_status"] == "missing")
    retired = sum(1 for i in indicators if i["freshness_status"].startswith("retired"))
    total = len(indicators)
    fresh_required = sum(1 for i in indicators if i["required"] and i["freshness_status"] == "fresh")
    total_required = sum(1 for i in indicators if i["required"])

    print(f"  5a  per-indicator status present:     {fmt(all('freshness_status' in i for i in indicators))}")
    print(f"      fresh={fresh}   missing={missing}   retired={retired}   total={total}")
    print(f"      required fresh: {fresh_required}/{total_required}")
    # Retired indicators must be blocked from current diagnostics
    bad_retired = [i["series_id"] for i in indicators
                   if i["freshness_status"].startswith("retired") and i["current_diagnostics_allowed"]]
    print(f"  5a  retired indicators blocked:       {fmt(not bad_retired)}   leak={bad_retired}")

    coverage = fresh_required / total_required if total_required else 0
    if coverage >= 0.9: quality = "high"
    elif coverage >= 0.5: quality = "limited"
    else: quality = "unreliable"
    print(f"  5b  required-coverage = {coverage:.0%} → '{quality}' quality")

    # Provenance: code_version + config_version + data_version (or equivalents)
    prov_map = {
        "code_version":   rm.get("code_version") or rm.get("git_commit"),
        "config_version": rm.get("config_version") or rm.get("config_hash"),
        "data_version":   rm.get("data_version") or rm.get("harvester_release"),
    }
    missing_prov = [k for k, v in prov_map.items() if not v]
    print(f"  5c  provenance triple complete:       {fmt(not missing_prov)}   missing={missing_prov}")
    for k, v in prov_map.items():
        print(f"        {k:15s} = {v}")

    # ---------------------------------------------------------------- summary
    print("\n" + "=" * 78)
    print(" SCORECARD")
    print("=" * 78)
    d1_any = sum(1 for eid,(exp,_) in EXPECTED.items() if exp in {family(first_to_cross(events_by_id[eid])), family(channel_window_max_leader(events_by_id[eid])), family(channel_at_peak_leader(events_by_id[eid]))})
    print(f"  D1  channel identification:  {d1_any}/{n} (any-definition)   "
          f"first-crosser only: {d1_first}/{n}")
    print(f"  D2  differentiation:         {pass_count} bins pass   C005 trio distinct: {len(set(fams.values()))==3}")
    print(f"  D3  self-calibration:        flags={fmt(d3a)} residuals={fmt(d3a_res)} "
          f"K-shortfall-flagged={fmt(d3b)}")
    print(f"  D4  lead-time (>=30d):       {d4_pass}/{d4_total}")
    print(f"  D5  data integrity:          coverage={quality}  "
          f"retired-blocked={fmt(not bad_retired)}  provenance={fmt(not missing_prov)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
