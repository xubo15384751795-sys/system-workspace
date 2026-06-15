# Canonical Drift Report

**Generated:** 2026-06-02
**Scope:** canonical_proxy_spec.yaml vs runtime code
**Auditor:** Hermes Agent (canonical-drift-auditor)

---

## Executive Summary

The canonical spec defines **4 voting channels: M, D, K, X_agg**. The codebase has a **P0 drift**: `singular_detector.py` still uses `X_PRE` / `X_REALIZED` as voting channels in `SigmaVector` and `_sigma_vector()`, while `build_sigma_vector()` in `semantic.py` correctly uses `X_agg`. Two separate sigma computation paths exist and disagree on channel structure.

---

## P0 — Critical Drift (Breaks Canonical Contract)

### DRIFT-001: SigmaVector uses X_PRE / X_REALIZED instead of X_agg

**File:** `Structural Deformation Research System/src/derivation/singular_detector.py`
**Lines:** L14-37 (class definition), L154-195 (_sigma_vector method)
**Status:** ✅ FIXED (Phase 1 + Phase 2, 2026-06-02)

```python
# CURRENT (non-canonical):
@dataclass
class SigmaVector:
    M: float
    D: float
    K: float
    X_PRE: float        # ← NOT a canonical voting channel
    X_REALIZED: float   # ← NOT a canonical voting channel
    operator_penalties: dict[str, float]
    dominant_channel: str
    cofire_count: int
    reduction_warning: str
```

**Canonical spec says (§4.1, §4.5):**
> X_PRE / X_REALIZED are NOT canonical. They are an engineering split that may be retained as derived layers, but cannot be voting channels.

**Impact:** The singular detector — the system's core threshold-hitting mechanism — votes on 5 channels (M, D, K, X_PRE, X_REALIZED) instead of 4 canonical channels (M, D, K, X_agg). `dominant_channel` and `cofire_count` are computed over the wrong channel set.

### DRIFT-002: _sigma_vector() builds non-canonical channel dict

**File:** `singular_detector.py` L162-168

```python
channels = {
    "M": float(self.w_mismatch * mismatch),
    "D": float(self.w_dof * dof_contraction),
    "K": float(self.w_curvature * curvature),
    "X_PRE": float(self.w_shadow * shadow_pre),        # ← should be X_agg
    "X_REALIZED": float(self.w_shadow * shadow_realized),  # ← derived diagnostic only
}
```

### DRIFT-003: compute_sigma_t() uses X_PRE not X_agg

**File:** `Workbench/src/workbench/c005_morphology_replay.py` L58-64

```python
def compute_sigma_t(channel_at_peak: dict[str, Any]) -> float:
    mismatch = max(float(channel_at_peak.get("M") or 0.0), 0.0)
    dof_contraction = max(float(channel_at_peak.get("D_contraction") or 0.0), 0.0)
    curvature = max(float(channel_at_peak.get("K") or 0.0), 0.0)
    shadow_pre = max(float(channel_at_peak.get("X_PRE") or 0.0), 0.0)  # ← should be X_agg
    return mismatch + dof_contraction + curvature + shadow_pre
```

Also references X_PRE in sigma_formula strings at L348 and L440.

---

## P1 — Significant Drift (Data Model Mismatch)

### DRIFT-004: ProxyReading has X_PRE / X_REALIZED as first-class fields

**File:** `Structural Deformation Research System/src/core/models.py` L49-60

```python
@dataclass(frozen=True)
class ProxyReading:
    M: Optional[float]
    D: Optional[float]
    K: Optional[float]
    X: Optional[float]
    X_PRE: Optional[float] = None       # ← derived diagnostic, not voting
    X_REALIZED: Optional[float] = None   # ← derived diagnostic, not voting
```

### DRIFT-005: MEASUREMENT_CHANNELS includes X_PRE / X_REALIZED

**File:** `Structural Deformation Research System/src/derivation/proxy_builder.py` L15-16

```python
MEASUREMENT_CHANNELS = ("M", "D", "K", "X_PRE", "X_REALIZED")  # ← should be (M, D, K, X_agg)
PUBLIC_CHANNELS = ("M", "D", "K", "X", "X_PRE", "X_REALIZED")  # ← X_PRE/X_REALIZED are diagnostic
```

### DRIFT-006: DEFAULT_DIRECT_CHANNEL_MAP maps X_PRE / X_REALIZED

**File:** `proxy_builder.py` L27-34

```python
DEFAULT_DIRECT_CHANNEL_MAP = {
    "X_PRE": "X_PRE_PROXY",       # ← diagnostic layer
    "X_REALIZED": "X_REALIZED_PROXY",  # ← diagnostic layer
}
```

### DRIFT-007: output_exporter iterates X_PRE / X_REALIZED as channels

**File:** `Structural Deformation Research System/src/output/output_exporter.py` L219

```python
for channel in ("M", "D", "K", "X_PRE", "X_REALIZED", "Sigma")  # ← should be canonical + Sigma
```

---

## P2 — Cosmetic / Test Drift

### DRIFT-008: Tests construct SigmaVector with X_PRE / X_REALIZED

**Files:**
- `tests/test_structural_layers.py` L61-65
- `tests/test_proxy_builder.py` L20, L63-68
- `tests/test_singular_detector.py` L70-71
- `tests/test_output_exporter.py` L200-201

### DRIFT-009: structural_replay_v2.py lists X_PRE / X_REALIZED as StateVariables

**File:** `scripts/structural_replay_v2.py` L220, L418-419, L445-446

```python
CHANNELS = ["M", "D_contraction", "K", "X_agg", "X_PRE", "X_REALIZED", "Pi_t"]
```

Note: This file correctly marks them as `canonical_status: "extension_beyond_canonical"` — the drift is in naming, not in voting status.

### DRIFT-010: Governance tests already enforce the rule (partially)

**File:** `tests/governance/test_canonical_proxy_alignment.py` L119-128

This test correctly blocks X_PRE/X_REALIZED from `canonical_voting` in the proxy registry, but does NOT check the singular detector's SigmaVector.

**File:** `tests/governance/test_semantic_registry.py` L49

```python
assert "X_PRE" not in vector and "X_REALIZED" not in vector
```

This test passes because `build_sigma_vector()` correctly uses X_agg — but it doesn't catch the detector drift.

---

## Consistent Code (No Drift)

| Component | Uses X_agg? | Status |
|-----------|-------------|--------|
| `canonical_proxy_spec.yaml` | ✅ X_agg as canonical | Reference |
| `semantic.py::build_sigma_vector()` | ✅ CANONICAL_CHANNELS = [M, D, K, X_agg] | Correct |
| `semantic.py::CANONICAL_CHANNELS` | ✅ [M, D, K, X_agg] | Correct |
| `test_sigma_vector.py` | ✅ Asserts X_PRE not in output | Correct |
| `test_canonical_proxy_alignment.py` | ✅ Blocks X_PRE/X_REALIZED voting | Correct |
| `test_semantic_registry.py` | ✅ Asserts X_PRE not in vector | Correct |

---

## Drift Map

```
canonical_proxy_spec.yaml          ✅ X_agg (canonical)
        ↓
build_sigma_vector() (semantic.py) ✅ X_agg (canonical)
        ↓
test_sigma_vector.py               ✅ Validates X_agg

singular_detector.py::SigmaVector  ❌ X_PRE + X_REALIZED (non-canonical)
        ↓
singular_detector.py::_sigma_vector ❌ Builds 5-channel dict
        ↓
compute_sigma_t() (c005)           ❌ Uses X_PRE
        ↓
output_exporter.py                 ❌ Iterates X_PRE/X_REALIZED
```

---

## Recommended Patch Plan

### Phase 1: Add X_agg to SigmaVector (non-breaking)
1. Add `X_agg: float` field to `SigmaVector` dataclass
2. Compute `X_agg = X_PRE + X_REALIZED` (or use `proxy.X`) in `_sigma_vector()`
3. Keep X_PRE / X_REALIZED as derived diagnostic fields
4. Add test: `assert vector.X_agg == vector.X_PRE + vector.X_REALIZED`

### Phase 2: Make X_agg the voting channel
1. Update `dominant_channel` to use [M, D, K, X_agg]
2. Update `cofire_count` to use [M, D, K, X_agg]
3. Update `compute_sigma_t()` to use X_agg
4. Update `output_exporter.py` channel iteration

### Phase 3: Deprecation markers
1. Add `# DEPRECATED: use X_agg for canonical voting` to X_PRE/X_REALIZED in SigmaVector
2. Add `@deprecated` decorator or warning to `_shadow_pre()` / `_shadow_realized()`
3. Keep ProxyReading.X_PRE / X_REALIZED for backward compat

### Phase 4: Tests
1. Add: `test_sigma_vector_uses_canonical_channels()` — asserts [M, D, K, X_agg]
2. Add: `test_sigma_vector_x_agg_combines_shadow()` — asserts X_agg = combined
3. Add: `test_compute_sigma_t_uses_x_agg()` — asserts compute_sigma_t uses X_agg
4. Update existing tests to include X_agg field

---

## Files to Touch

| File | Change |
|------|--------|
| `singular_detector.py` | Add X_agg to SigmaVector, update _sigma_vector() |
| `c005_morphology_replay.py` | Update compute_sigma_t() to use X_agg |
| `output_exporter.py` | Update channel iteration |
| `proxy_builder.py` | Add X_agg computation from X_PRE + X_REALIZED |
| `core/models.py` | Add X_agg to ProxyReading (optional) |
| `test_singular_detector.py` | Add X_agg assertions |
| `test_sigma_vector.py` | Add detector-side X_agg test |

---

## Auto-fix Recommendation

**Phase 1 (add X_agg)**: ✅ Safe to auto-fix — additive, non-breaking
**Phase 2 (switch voting)**: ⚠️ Manual review required — changes detector behavior
**Phase 3 (deprecation)**: ✅ Safe to auto-fix — markers only
**Phase 4 (tests)**: ✅ Safe to auto-fix — additive tests
