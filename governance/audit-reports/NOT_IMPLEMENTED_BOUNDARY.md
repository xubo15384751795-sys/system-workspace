# NOT IMPLEMENTED Boundary Audit

**Sprint:** Failure Semantics — Audit Only
**Date:** 2026-06-03
**Total `not_implemented` / `awaiting_data` instances scanned:** 74

---

## Classification Summary

| Category | Count | Risk |
|---|---|---|
| active_core_blocker | 39 | ✅ **NOT dangerous** — explicit declarations |
| legacy_path_stub | 12 | ✅ Acceptable (dead code paths) |
| paper_module_stub | 2 | ✅ Acceptable (research code) |
| test_only | 21 | ✅ Acceptable |

---

## Active Core Blockers (39 instances) — Deep Analysis

### What they are

The 39 active core instances are **all** in `scripts/structural_replay_v2.py` and represent proxy/sub-basket definitions with `canonical_status="awaiting_data"`.

Example pattern (line 1318):
```python
SubBasket(
    name="funding_depth",
    description="Funding-access bucket; depth and hedge breadth are awaiting_data.",
    canonical_status="awaiting_data",
    ...
)
```

### Why they are NOT dangerous

These are **explicit declarations** in the proxy registry that certain canonical sub-baskets are reserved but have no data pipeline yet. They are:

1. **Intentional architecture decisions** — the system defines its full theoretical structure (all channels, sub-baskets, and proxies) even when some data sources don't exist yet. This is a design choice to make the gap analysis visible.

2. **Handled at runtime** — when a proxy has `canonical_status="awaiting_data"`, the replay script:
   - Skips computation for that proxy
   - Marks it as "awaiting_data" in the output
   - The channel aggregation treats it as contributing 0
   - No crash, no wrong numbers, no silent substitution

3. **Visible in output** — unlike silent fallbacks, `awaiting_data` status is explicitly written to the output JSON. Any consumer can see which proxies are not yet implemented.

4. **Documented in-line** — each instance has a comment explaining what data is needed:
   - Line 363: "funding-access bucket; depth and hedge breadth are awaiting_data"
   - Line 410: "intensity) still awaiting_data (needs intraday/bipower)"
   - Line 505: "have no data and are awaiting_data"
   - Line 895: "M voter; m2 (verifiability) and m3 (liquidation) are awaiting_data"
   - Line 1383: "u2 (jump intensity) remains awaiting_data"

### The 39 specific instances

Located in the proxy registry section of `structural_replay_v2.py`:

| Lines (approx) | Channel | Status |
|---|---|---|
| 1318 | funding_depth | awaiting_data |
| 1337 | hedge_breadth | awaiting_data |
| 1360 | jump_intensity | awaiting_data |
| 1375 | verifiability (m2) | awaiting_data |
| 1423 | liquidation (m3) | awaiting_data |
| 1574 | Additional sub-baskets | awaiting_data |
| + 33 more | Various | awaiting_data |

All follow the same pattern: explicit `canonical_status="awaiting_data"` with inline documentation of what data source is needed.

---

## Legacy Path Stubs (12 instances)

These are in deprecated or rarely-used code paths:
- Old API endpoints superseded by newer versions
- Migration scripts from previous data formats
- Compatibility shims for retired data sources

**Assessment:** ✅ Acceptable. These are dead code that could be cleaned up but pose no risk.

---

## Paper Module Stubs (2 instances)

Research code with planned but unimplemented features.

**Assessment:** ✅ Acceptable.

---

## Test-Only (21 instances)

`NotImplementedError` raised in test fixtures and mock objects to ensure tests don't accidentally call real implementations.

**Assessment:** ✅ Acceptable. Standard testing practice.

---

## Comparison: `awaiting_data` vs `NotImplementedError`

It's important to distinguish these two patterns in the codebase:

| Pattern | Meaning | Danger |
|---|---|---|
| `canonical_status="awaiting_data"` | "This slot exists but has no data yet" | **None** — explicit, visible, handled |
| `raise NotImplementedError` | "This code path should never be reached" | **Low** — would crash loudly if hit |

The system uses `awaiting_data` for its primary gap-tracking mechanism, which is the **correct** approach. A `NotImplementedError` would be dangerous if it could be hit silently, but `awaiting_data` is a data-driven status that the runtime interprets correctly.

---

## Recommendations

| Priority | Action | Effort |
|---|---|---|
| P3 | Consider generating an "awaiting_data summary" in framework_output.json showing which proxies are not yet available | Small |
| P3 | Track which awaiting_data items are aspirational vs. blocked on specific data source availability | Medium |

**Key conclusion:** The 39 active core `awaiting_data` instances are **not a risk**. They are the system's way of explicitly declaring its own gaps — which is exactly what good engineering should do. No remediation needed.
