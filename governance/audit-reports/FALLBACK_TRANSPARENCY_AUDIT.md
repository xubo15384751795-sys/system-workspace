# Fallback Transparency Audit

**Sprint:** Failure Semantics — Audit Only (no code changes)
**Date:** 2026-06-03
**Total fallbacks scanned:** 102

---

## Classification Summary

| Category | Count | Risk |
|---|---|---|
| dangerous_silent_fallback | 20 | P1 (3 flagged below) |
| legitimate_degradation | 39 | ✅ Acceptable |
| paper_module_fallback | 38 | ✅ Acceptable (research code) |
| test_only | 5 | ✅ Acceptable |

---

## Dangerous Silent Fallbacks (20 instances)

These are fallbacks in active core paths that execute without logging a warning. We assessed each individually.

### Truly Dangerous — P1 (3 items)

These don't produce wrong numbers but **mask the true data source**, making it impossible to know from output alone whether primary data was used.

#### 1. `current.py:155-184` — state_fallbacks dict
```python
_state_fallbacks = {
    "morphology": ("pattern", "unknown"),
    "sigma": ("sigma_t", None),
    "singular_flag": ("singular_flag", None),
    "singular_regime": ("singular_flag", None),
    "leading_channel": ("leading_channel", "unknown"),
}
```
**Risk:** When the main signal payload doesn't contain a capability value, this silently falls back to `state` dict values with default fallbacks. For `morphology` and `leading_channel`, the default `"unknown"` is reasonable. But `sigma` falling back to `sigma_t` from state silently swaps data source without any trace in the output.
**Severity:** P1 — data source attribution is lost. The consumer cannot tell if `sigma` came from the signal payload or from a state fallback.
**Recommendation:** Add a `_source` annotation per capability in the advanced dict.

#### 2. `h41.py:130-136` — FRED fallback for H41 data
```python
if result.fetch_error and self._allow_fred_fallback:
    fred_sid = H41_FRED_MAP.get(sid)
    if fred_sid and self._api_key:
        fallback = self._fetch_via_fred(fred_sid, sid)
        if not fallback.fetch_error:
            fallback.fetch_fallback_reason = f"direct_h41_ddp_failed: {result.fetch_error}"
        result = fallback
```
**Risk:** When the primary H41 DDP feed fails, this silently switches to FRED as the data source. While `fetch_fallback_reason` is set on the result, downstream consumers in the replay pipeline don't surface this metadata in `framework_output.json`. The output appears as if H41 data was obtained normally.
**Severity:** P1 — data provenance is tracked internally but invisible in output. Two different data sources produce indistinguishable output.
**Recommendation:** Surface `fetch_fallback_reason` in the output metadata.

#### 3. `official.py:617-621` — quality_flag_label returns string "fallback"
```python
def _quality_flag_label(value: Any) -> str:
    if value in {0, "0", "ok"}:
        return "observed"
    if value in {1, "1"}:
        return "fallback"
    if value in {2, "2"}:
        return "error"
```
**Risk:** This is a labeling function, not a control flow issue. It correctly maps quality flag `1` to the label `"fallback"`. However, the string `"fallback"` is returned as a plain value without any structured metadata — consumers must know to interpret this string. This is **less dangerous** than the other two because it's transparent (the label literally says "fallback").
**Severity:** P1 (low) — the label is correct but could be missed in unstructured output.

### Acceptable Silent Fallbacks (17 items)

The remaining 17 "dangerous_silent_fallback" instances fall into patterns that are **acceptable** upon review:

| # | File:Line | Pattern | Why Acceptable |
|---|---|---|---|
| 4 | `proxy_builder.py:106` | `_basket_score` returns None on missing data | Caller `_component` propagates None → channel contributes 0. Documented behavior. |
| 5 | `proxy_builder.py:140` | `_rolling_zscore` returns None | Same pattern — caller handles None gracefully. |
| 6 | `proxy_builder.py:146` | `_latest_float` returns None | Same — downstream correctly treats as missing. |
| 7 | `freshness.py` | `parse_timestamp` returns None on malformed input | Caller checks for None before use. |
| 8 | `freshness.py` | `parse_date` returns None | Same pattern. |
| 9 | `evidence_dashboard.py` | `_point_at_or_before` returns None | Caller skips None points in aggregation. |
| 10 | `structural_replay_v2.py:617` | `_series` returns None when column missing | Caller propagates → proxy contributes 0. Core design. |
| 11 | `structural_replay_v2.py:625` | `_spread` returns None when either leg missing | Same — intentional degradation. |
| 12 | `structural_replay_v2.py:640` | `_butterfly` returns None | Same pattern. |
| 13 | `structural_replay_v2.py:725` | `_rolling_zscore` returns None on None input | Guard clause, not a fallback. |
| 14 | `structural_replay_v2.py:796` | `_component` returns None | Propagates upstream None correctly. |
| 15 | `semantic.py` | Capability resolution fallback | Falls back between equivalent capability IDs. |
| 16 | `output_exporter.py:180,183` | Panel lookup returns None | Caller treats as "no data for this proxy". |
| 17 | `singular_detector.py` | Detection fallback on missing inputs | Returns conservative default (no detection). |
| 18-20 | Various proxies/ | Series lookup fallbacks | All follow the None-propagation pattern. |

**Assessment:** All 17 are **documented degradation patterns** where the caller correctly handles the None/missing case. No silent data corruption occurs.

---

## Legitimate Degradation (39 instances)

These are explicitly documented fallbacks with clear semantics:
- Default values for optional configuration
- Graceful degradation when optional data sources are unavailable
- Fallback chains that log their path

## Paper Module Fallbacks (38 instances)

Research/exploratory code with expected incomplete implementations. Not in active data paths.

## Test-Only Fallbacks (5 instances)

Only exercised in test contexts. No production risk.

---

## Recommendations

| Priority | Action | Effort |
|---|---|---|
| P1 | Surface `fetch_fallback_reason` from h41.py into framework_output.json metadata | Small |
| P1 | Add `_source` annotation to state_fallback values in current.py | Small |
| P1 (low) | Consider structured quality flag enum instead of string "fallback" | Trivial |
| P2 | Add optional warning log when state_fallbacks activates | Trivial |

**Key finding:** Of 102 fallbacks, only 3 are P1 — and none are P0. The system's fallback design is largely sound; the gaps are in **observability** (data source attribution), not in **correctness** (wrong numbers).
