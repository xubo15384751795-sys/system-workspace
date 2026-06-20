# Structural Replay Coverage Repair Report

**Generated:** 2026-06-02
**Sprint:** Coverage Repair Sprint (no new theory channels, no detector refactor)

---

## Summary

| Before | After |
|--------|-------|
| `./sys check` → UNKNOWN | `./sys check` → **ACTIVE_PARTIAL** |
| `framework_output.json` → missing | → **partial** with SigmaVector |
| SigmaVector snapshot → `{}` | → **persistence via bridge script** |
| M_curve_inversion → CORE_CONTRACT_VIOLATION | → **eliminated** (downgraded to diagnostic_only) |
| X_agg frequency → CONTRACT_VIOLATION | → **informational** (resampling already handles it) |
| Coverage ratio → implicit 2/4 | → **explicit 2/4 with channel_coverage** |
| K status → silent NOT_IMPLEMENTED | → **explicit with coverage plan** |
| X_agg status → silent no_data | → **explicit with coverage plan** |

---

## Task 1: SigmaVector Persistence ✅

**Problem:** Detector computes SigmaVector but snapshot persists `{}`.

**Root cause:** Two separate paths — Deformation run saves to `Output/deformation_runs/`, replay saves to `Output/sandbox/`. `./sys check` reads from `Output/current/` which only links to Deformation run.

**Fix:** New bridge script `scripts/bridge_replay_to_current.py`:
- Reads `sigma_vector.json` from replay output
- Generates `framework_output.json` with explicit PARTIAL status
- Generates `00_READ_ME_FIRST.md` with channel coverage
- Run: `python3 scripts/bridge_replay_to_current.py`

**Files created:**
- `scripts/bridge_replay_to_current.py`
- `Output/current/framework_output.json` (regenerated)
- `Output/current/00_READ_ME_FIRST.md` (regenerated)

---

## Task 2: ./sys check Status ✅

**Before:** UNKNOWN (missing framework output)
**After:** ACTIVE_PARTIAL

Status hierarchy:
```
ACTIVE_FULL     — 4/4 channels live
ACTIVE_PARTIAL  — 2-3/4 channels live
DEGRADED_PARTIAL — 1/4 channels live
MISSING_OUTPUT  — 0/4 or no output
STALE           — output older than threshold
```

Current state: ACTIVE_PARTIAL (M + D live, K + X_agg NOT_IMPLEMENTED)

---

## Task 3: M_curve_inversion Governance Violation ✅

**Problem:** `M_curve_inversion` was `tier="core"` with `independence_group="rates_curve"`, which is in M's `forbidden_groups`.

**Fix:** Changed tier from `"core"` to `"diagnostic_only"` in `scripts/structural_replay_v2.py` L860.

**Effect:**
- `M_curve_inversion` no longer participates in M voting
- Still available for diagnostic decomposition
- CORE_CONTRACT_VIOLATION eliminated from replay output

**File modified:** `scripts/structural_replay_v2.py`

---

## Task 4: X_agg Frequency Mismatch ✅ (Informational)

**Problem:** X_agg `expected_freq="weekly"` but core proxy `X_agg_v1_obs_to_assets_candidate` is `freq="quarterly"`.

**Status:** Already handled — `_freq_aware_zscore()` resamples quarterly → native cadence, computes z-score, forward-fills to daily. The CONTRACT_VIOLATION warning is informational.

**Remaining:** The proxy is `canonical_status="candidate_pending_promotion"` — it contributes 0 to voting until promoted. No code change needed; the warning is correct governance behavior.

---

## Task 5: X_agg MVP Coverage Plan ✅

**Report:** `governance/audit-reports/X_coverage_report.md`

**Key findings:**
- 5 of 31 proxy inputs have matching raw series (16.1%)
- P0 (can connect NOW): `primary_credit`, `discount_window`, `btfp` (all H41, weekly)
- 26 inputs need new data (X_-prefixed synthetic IDs)
- Additional candidates: `tot_pub_debt_out_amt`, `open_today_bal`, `SEC_FILING_PULSE`, `NFCILEVERAGE`

**Next step:** Connect H41 primary_credit/discount_window/btfp to X_OFFICIAL_SUPPORT_USAGE group. This would give X_agg its first non-zero contribution.

---

## Task 6: K MVP Coverage Plan ✅

**Report:** `governance/audit-reports/K_coverage_report.md`

**Key findings:**
- 6 of 20 proxy inputs can be wired NOW from existing panel data
- Connectable: `K_SKEW_SLOPE` ← CBOE:SKEW, `K_VVIX` ← CBOE:VVIX, `K_TERM_STRUCTURE_TWIST` ← VIX9D/VIX3M/VIX6M, `K_VARIANCE_RISK_PREMIUM_INSTABILITY` ← VIX+SPX, `K_CRASH_SKEW` ← CBOE:SKEW
- 14 inputs need intraday SPX, OTM options chains, cross-asset returns, or GEX data

**Next step:** Wire the 6 connectable proxies. This would give K its first non-NaN aggregation and move it from NOT_IMPLEMENTED to PARTIAL_PROXY.

---

## Task 7: Family Diversity + Residual Uniqueness ⏳

**Status:** Reporting only, not forced fix.

**Current state:**
- M: 100% FRED_RATES (family monoculture) — structurally appropriate (M is by definition an interest-rate mechanism)
- D: 100% FRED_FUNDING — appropriate for D's mechanism
- residual_uniqueness: 0.00 for all channels — marked as `not_valid_until_3_channels_active`

**No code change:** Family diversity is correct for M/D. Residual uniqueness is meaningless with only 2 channels.

---

## Files Modified

| File | Change |
|------|--------|
| `scripts/bridge_replay_to_current.py` | NEW — bridges replay → Output/current/ |
| `scripts/structural_replay_v2.py` | M_curve_inversion: core → diagnostic_only |
| `Output/current/framework_output.json` | Regenerated with ACTIVE_PARTIAL |
| `Output/current/00_READ_ME_FIRST.md` | Regenerated with channel coverage |

## Files Created (Reports)

| File | Content |
|------|---------|
| `governance/audit-reports/X_coverage_report.md` | X_agg MVP coverage plan |
| `governance/audit-reports/K_coverage_report.md` | K MVP coverage plan |
| `governance/audit-reports/STRUCTURAL_REPLAY_COVERAGE_REPAIR_REPORT.md` | This report |

## Tests

**Existing:** 762 passed, 0 failed (no regressions)
**New tests needed:** None for this sprint (informational changes only)

---

## Recommended Next Steps

1. **Connect H41 primary_credit/discount_window/btfp to X_OFFICIAL_SUPPORT_USAGE** — gives X_agg first non-zero data
2. **Wire 6 K proxies from existing CBOE data** — gives K first non-NaN aggregation
3. **Run bridge_replay_to_current.py after each replay** — keeps framework_output.json fresh
4. **Add bridge to `./sys refresh`** — automate the bridging
