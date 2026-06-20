# Return None Classification

**Sprint:** Failure Semantics — Audit Only
**Date:** 2026-06-03
**Total `return None` scanned:** 241

---

## Classification Summary

| Category | Count | Risk |
|---|---|---|
| missing_data_signal (active core) | 54 | ✅ Legitimate — callers handle it |
| paper_module_stub | 42 | ✅ Acceptable (research code) |
| legitimate_optional | 140 | ✅ Normal optional return pattern |
| test_only | 5 | ✅ Acceptable |

**Key finding:** Zero truly dangerous `return None` instances. The 54 active core returns all follow the **None-propagation pattern** — a well-established design where `None` means "no data available" and callers treat it as "contribute nothing."

---

## Active Core None Returns (54 instances) — Deep Analysis

### Pattern 1: Series/Spread/Butterfly Lookup (structural_replay_v2.py)

The core replay script has ~11 `return None` instances in its data lookup functions:

| File:Line | Function | Purpose |
|---|---|---|
| `structural_replay_v2.py:617` | `_series(panel, col)` | Returns None when column not in panel |
| `structural_replay_v2.py:625` | `_spread(panel, left, right)` | Returns None when either leg is missing |
| `structural_replay_v2.py:640` | `_butterfly(panel, short, mid, long)` | Returns None when any tenor is missing |
| `structural_replay_v2.py:725` | `_rolling_zscore(series)` | Returns None when input series is None |
| `structural_replay_v2.py:796` | `_component(series)` | Returns None when input is None |
| `structural_replay_v2.py:811` | `_pct_component(series)` | Returns None when input is None |
| `structural_replay_v2.py:817` | `_level_component(series)` | Returns None when input is None |
| `structural_replay_v2.py:831` | `_clipped_component(series)` | Returns None when input is None |
| `structural_replay_v2.py:845` | `_activation_component(series)` | Returns None when input is None |
| `structural_replay_v2.py:851` | `_latest_float(series)` | Returns None when series is empty |

**Caller handling:** All of these are called in the proxy computation pipeline. When a proxy returns None, the channel aggregation treats it as a zero contribution — the channel score is computed from whatever proxies *do* have data. This is **intentional graceful degradation**: a missing series doesn't crash the system or produce wrong numbers; it simply doesn't contribute.

**Assessment:** ✅ **LEGITIMATE.** This is the correct design for a system that processes many data series where some may be unavailable for certain time windows.

### Pattern 2: Proxy Builder (proxy_builder.py)

| File:Line | Function | Purpose |
|---|---|---|
| `proxy_builder.py:106` | `_basket_score()` | Returns (None, scores) when insufficient data |
| `proxy_builder.py:140` | `_rolling_zscore()` | Returns None on None input |
| `proxy_builder.py:146` | `_rolling_zscore()` | Returns None on empty series |
| `proxy_builder.py:157` | `_latest_float()` | Returns None on empty series |
| `proxy_builder.py:161` | `_latest_float()` | Returns None on all-NaN series |
| `proxy_builder.py:220` | Top-level builder | Returns None when proxy cannot be built |

**Caller handling:** The replay script checks `if proxy is not None` before adding to the channel. Missing proxies are logged in the audit trail.

**Assessment:** ✅ **LEGITIMATE.**

### Pattern 3: Freshness Parsing (freshness.py)

| File:Line | Function | Purpose |
|---|---|---|
| `freshness.py` | `parse_timestamp()` | Returns None on malformed timestamp string |
| `freshness.py` | `parse_date()` | Returns None on malformed date string |

**Caller handling:** Freshness checks treat None as "unknown freshness" — the item is flagged for review, not silently accepted.

**Assessment:** ✅ **LEGITIMATE.**

### Pattern 4: Evidence Dashboard (evidence_dashboard.py)

| File:Line | Function | Purpose |
|---|---|---|
| `evidence_dashboard.py` | `_point_at_or_before()` | Returns None when no data point exists before target date |

**Caller handling:** Aggregation loop skips None values. Dashboard shows "no data" rather than crashing.

**Assessment:** ✅ **LEGITIMATE.**

### Pattern 5: Output Exporter (output_exporter.py)

| File:Line | Function | Purpose |
|---|---|---|
| `output_exporter.py:180` | Panel lookup | Returns None when series not in panel |
| `output_exporter.py:183` | Panel lookup | Returns None when panel is empty |

**Caller handling:** Exporter writes "N/A" or omits the field.

**Assessment:** ✅ **LEGITIMATE.**

---

## Paper Module Stubs (42 instances)

Research/exploratory modules with placeholder implementations. These are in:
- `deformation-framework/src/research/` — scenario generators, experimental analyzers
- `deformation-framework/src/dynamic/` — dynamic risk models under development
- `system-learning-hub/` — learning/analytics infrastructure

None are in active data paths. Acceptable for research code.

---

## Legitimate Optional Returns (140 instances)

Standard Python patterns where `None` is the natural return for "no value":
- Dictionary `.get()` defaults
- Optional parameter handling
- Early-return guards for invalid input
- Configuration lookups with no default set

These are idiomatic Python and require no remediation.

---

## Recommendations

| Priority | Action | Effort |
|---|---|---|
| P3 | Consider adding a `MissingDataSentinel` type instead of bare None for the series lookup functions, to distinguish "no data" from "bug" | Medium |
| P3 | Add a debug-level log when `_series()` returns None in the replay script (currently silent) | Trivial |

**Key conclusion:** The `return None` pattern in active core is a **well-designed degradation strategy**, not a bug risk. The None-propagation chain from `_series` → `_spread`/`_butterfly` → `_component` → channel aggregation is consistent and correct. No remediation needed.
