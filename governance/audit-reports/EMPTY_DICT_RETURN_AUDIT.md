# Empty Dict Return Audit

**Sprint:** Failure Semantics — Audit Only
**Date:** 2026-06-03
**Total `return {}` scanned:** 33

---

## Classification Summary

| Category | Count | Risk |
|---|---|---|
| empty_artifact_risk (active core) | 7 | P2 (see assessment) |
| empty_config_ok | 26 | ✅ Acceptable |
| test_only | 0 | — |

---

## Active Core Empty Dict Returns (7 instances) — Deep Analysis

### 1. `structural_replay_v2.py:2209` — Proxy metadata fallback

```python
        return {}
```

**Context:** Returns an empty dict when proxy metadata cannot be constructed (e.g., the proxy definition is incomplete or the data source is unavailable).

**Risk assessment:** The caller uses `.get()` on the returned dict, so an empty dict is handled identically to a dict with missing keys — values default to None/absent. The downstream output serializer omits fields that aren't present.

**Verdict:** ✅ **Acceptable.** No silent data corruption. Missing fields are simply absent from output.

### 2. `bridge_replay_to_current.py:71` — Bridge output fallback

```python
        return {}
```

**Context:** Returns empty dict when the bridge cannot map replay output to current format (e.g., missing required fields in replay output).

**Risk assessment:** The caller in `refresh_output_current.py` merges this with other data using `dict.update()`. An empty dict means "no bridge data" — the current output retains whatever it had before.

**Verdict:** ✅ **Acceptable.** Graceful degradation.

### 3. `models.py:592` — Model serialization

```python
        return {}
```

**Context:** Returns empty dict when a model instance has no serialized representation (e.g., an abstract/uninitialized model).

**Risk assessment:** The caller checks `if result:` before using the dict. An empty dict is falsy, so it's treated as "no model data."

**Verdict:** ✅ **Acceptable.**

### 4. `models.py:625` — Model parameters

```python
        return {}
```

**Context:** Returns empty dict when model has no tunable parameters or parameters haven't been set.

**Risk assessment:** Used in parameter display/export. An empty dict shows "no parameters" which is accurate.

**Verdict:** ✅ **Acceptable.**

### 5. `run_viewer.py:146` — Run viewer data

```python
    return {}
```

**Context:** Returns empty dict when a run has no viewer data (e.g., run didn't complete or artifacts were cleaned up).

**Risk assessment:** The UI layer checks for empty dict and shows "No data available." No silent failure.

**Verdict:** ✅ **Acceptable.**

### 6. `run_viewer.py:151` — Run viewer nested data

```python
        return {}
```

**Context:** Nested lookup within run viewer — returns empty when a sub-section of the run data is missing.

**Risk assessment:** Same as above — UI handles empty gracefully.

**Verdict:** ✅ **Acceptable.**

### 7. `assembly.py:332` — Runtime assembly

```python
        return {}
```

**Context:** Returns empty dict when a runtime assembly step produces no output (e.g., all proxies in the assembly returned None).

**Risk assessment:** The downstream pipeline merges assembly outputs. An empty dict means this assembly step contributes nothing — consistent with the None-propagation pattern but using dict instead of None.

**Verdict:** ✅ **Acceptable.** This is the dict-equivalent of the `return None` pattern.

---

## Empty Config Returns (26 instances)

These are in configuration loading, schema validation, and settings management code:

| Location | Pattern | Why Acceptable |
|---|---|---|
| `schema.py:123` | Returns {} when schema section is missing | Caller uses `.get()` with defaults |
| `bridge.py:261,273` | Returns {} when data bridge has no mapping | Caller checks `if mapping:` |
| `data_hub_lite.py:891` | Returns {} when cache miss | Caller fetches fresh data |
| `artifact_navigator.py:22,26` | Returns {} when no artifacts found | UI shows "empty" state |
| `event_consumer.py:59,66` | Returns {} when no events to process | Normal idle state |
| `task_router.py:287,291` | Returns {} when no routing match | Caller uses fallback routing |
| `recurrence.py:296` | Returns {} when recurrence analysis has no results | Caller shows "no patterns" |

All 26 follow the standard pattern of returning an empty dict as a valid "nothing here" signal. Callers handle it correctly.

---

## Recommendations

| Priority | Action | Effort |
|---|---|---|
| P3 | Consider whether `run_viewer.py` should return `None` instead of `{}` to distinguish "no data" from "empty data" | Trivial |
| P3 | Document the convention: `{}` means "no data available" vs `None` means "could not compute" | Trivial |

**Key conclusion:** All 33 `return {}` instances are acceptable. The active core uses empty dicts as a consistent "no data" signal, and all callers handle it correctly. No remediation needed.
