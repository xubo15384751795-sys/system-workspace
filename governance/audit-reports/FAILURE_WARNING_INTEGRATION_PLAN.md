# Failure Warning Integration Plan

**Sprint:** Failure Semantics — Audit Only (no code changes)
**Date:** 2026-06-03

---

## Problem

The system has multiple silent degradation patterns:
- **Fallbacks** that switch data sources without surfacing the switch
- **Return None** when data is missing (handled correctly but invisibly)
- **Empty dicts** when no data is available
- **awaiting_data** status for unimplemented proxies

While callers handle all of these correctly (no wrong numbers, no crashes), the **output artifact** (`framework_output.json`) doesn't tell the consumer which degradation paths were taken. A human reading the output cannot distinguish "all primary data was available" from "3 proxies fell back to alternative sources and 2 returned no data."

---

## Recommendation

Add three new fields to the `advanced` section of `framework_output.json`:

### Proposed Schema Extension

```json
{
  "advanced": {
    "morphology": "inversion",
    "sigma": 2.3,
    "singular_flag": 0,
    "...": "...",

    "_data_quality": {
      "fallback_used": [
        {
          "proxy": "h41_treasury_10y",
          "source": "fred",
          "reason": "direct_h41_ddp_failed: HTTP 503",
          "file": "h41.py:135"
        }
      ],
      "missing_data": [
        {
          "proxy": "funding_depth",
          "status": "awaiting_data",
          "reason": "No intraday data pipeline"
        },
        {
          "proxy": "jump_intensity_u2",
          "status": "awaiting_data",
          "reason": "Needs bipower variation data"
        }
      ],
      "empty_artifact": [
        {
          "proxy": "hedge_breadth",
          "reason": "All component series returned None"
        }
      ],
      "state_fallback_used": [
        {
          "capability": "sigma",
          "from": "signal_payload",
          "to": "state.sigma_t",
          "file": "current.py:182-185"
        }
      ],
      "summary": {
        "total_proxies": 24,
        "primary_data": 19,
        "fallback_data": 1,
        "missing_data": 3,
        "empty_artifact": 1,
        "data_completeness_pct": 83.3
      }
    }
  }
}
```

### Field Definitions

| Field | Type | Description |
|---|---|---|
| `fallback_used` | `list[dict]` | Proxies that used an alternative data source (e.g., FRED instead of H41 DDP) |
| `missing_data` | `list[dict]` | Proxies with `awaiting_data` or `None` returns |
| `empty_artifact` | `list[dict]` | Proxies that produced an empty result (all component series missing) |
| `state_fallback_used` | `list[dict]` | Capabilities resolved via state fallback instead of signal payload |
| `summary` | `dict` | Aggregate counts for quick assessment |

---

## Implementation Touchpoints

### 1. Fallback Tracking (h41.py)

**Current state:** `fetch_fallback_reason` is set on `ProviderResult` but not surfaced.
**Change:** After replay completes, scan all `ProviderResult` objects for non-null `fetch_fallback_reason` and emit to `_data_quality.fallback_used`.

**Effort:** Small — add a post-processing step in `structural_replay_v2.py`.

### 2. State Fallback Tracking (current.py)

**Current state:** `_state_fallbacks` silently maps capabilities to state values.
**Change:** When `_state_fallbacks` activates (line 182-185), record which capability was resolved via state fallback.

**Effort:** Small — add a list accumulator in `_build_advanced_section()`.

### 3. Missing Data Tracking (structural_replay_v2.py)

**Current state:** `None` returns are propagated silently. `awaiting_data` status is in the proxy registry but not aggregated.
**Change:** After proxy computation, collect all proxies that returned None or have `awaiting_data` status.

**Effort:** Small — the replay script already has an audit dict; extend it.

### 4. Empty Artifact Tracking (various)

**Current state:** Empty dict returns are handled silently.
**Change:** Track when proxy output is `{}` or all-None Series.

**Effort:** Small — add a check in the output aggregation step.

---

## Priority Assessment

| What | Silent today? | Wrong numbers? | Priority |
|---|---|---|---|
| H41→FRED fallback | Yes (internally tracked, not surfaced) | No | P1 |
| state_fallbacks in current.py | Yes | No | P1 |
| quality_flag "fallback" string | No (labeled) | No | P1 (low) |
| None propagation | Yes (by design) | No | P2 |
| awaiting_data status | No (explicit) | No | P3 |
| Empty dict returns | Yes (by design) | No | P3 |

**Only P0 if:** A silent failure path produces **wrong numbers** in the active output. Our audit found **zero** such cases. All silent patterns either:
- Produce no number at all (None → missing), or
- Produce the correct number from an alternative source (fallback), or
- Produce a correct default (state fallback)

---

## Rollout Plan

| Phase | Scope | Effort |
|---|---|---|
| Phase 1 | Add `_data_quality` section with `summary` only (aggregate counts) | 1-2 hours |
| Phase 2 | Populate `fallback_used` and `state_fallback_used` lists | 2-3 hours |
| Phase 3 | Populate `missing_data` and `empty_artifact` lists | 2-3 hours |
| Phase 4 | Add `data_completeness_pct` to top-level output for dashboard integration | 1 hour |

**Total estimated effort:** 1 day

---

## What NOT to Do

1. **Don't raise severity to P0** — None of these patterns produce wrong numbers. P0 is reserved for "output is factually incorrect."
2. **Don't add warning logs for None propagation** — The _series/_spread/_butterfly pattern is called hundreds of times per run. Logging each None would be noise.
3. **Don't change the None-propagation pattern** — It's the correct design. The fix is observability, not behavior change.
4. **Don't block on this** — The system works correctly today. This plan adds visibility, not correctness.

---

## Key Conclusion

The system's failure semantics are **fundamentally sound**. The architecture correctly handles missing data through None-propagation, explicit `awaiting_data` status, and fallback chains. The only gap is **observability** — the output doesn't tell you which degradation paths were taken. This plan closes that gap without changing any runtime behavior.

**Severity of the gap:** Low. The system produces correct output. The improvement is diagnostic, not corrective.
