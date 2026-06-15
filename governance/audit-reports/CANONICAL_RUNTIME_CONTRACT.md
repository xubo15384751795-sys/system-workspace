# Canonical Runtime Contract

**Date:** 2026-06-03  
**Sprint:** Canonical Runtime + Status Hardening  
**Status:** ACTIVE — 8 tests enforce

## Canonical Voting Channels

The canonical voting channel set is **M, D, K, X_agg** (4 channels).

| Channel | Spec Section | Role |
|---------|-------------|------|
| M | §4.2 + §7.2.4 | Macro pressure |
| D | §4.3 + §7.2.1 | Deformation |
| K | §4.4 + §7.2.2 | Options-derived (VIX/VVIX/SKEW) |
| X_agg | §4.5 + §7.2.3 | Aggregate external stress |

## X_PRE / X_REALIZED: Diagnostic Only

`X_PRE` and `X_REALIZED` are **diagnostic channels** (Finance-2.tex §4.5). They must **never** have `canonical_status="canonical_voting"` with `tier="core"` or `tier="auxiliary"`.

**Enforced by:** `tests/governance/test_canonical_runtime_contracts.py::test_active_path_no_x_pre_x_realized_voting` (line 45)

## Active Sigma Computation Paths

### Path A: Canonical (active)
- **Function:** `workbench/governance.semantic::build_sigma_vector()`
- **Called by:** `scripts/structural_replay_v2.py` (line 2975) and `scripts/bridge_replay_to_current.py` (line 68 via `_load_sigma_vector()`)
- **Channels:** `[M, D, K, X_agg]` — matches `CANONICAL_CHANNELS`
- **Status:** ✅ Active, tested

### Path B: Legacy adapter
- **Class:** `Structural Deformation Research System/src/derivation/singular_detector.py::SigmaVector` (line 14)
- **Uses:** `X_PRE`, `X_REALIZED` instead of `X_agg`
- **Status:** ⚠️ Legacy/adapter — kept for backward compatibility but NOT used in canonical output path

## Schema Contract

`governance/framework_output.schema.json` defines the required structure:

- `advanced.sigma_vector` must contain: `M`, `D`, `K`, `X_agg`, `channels_live`, `channels_not_implemented`, `complete`, `dominant_channel`, `cofire_count`
- `basic.quality_status` enum: `FULL_HIGH_CONFIDENCE`, `FULL_PROXY_REDUCED`, `FULL_WITH_WARNINGS`, `PARTIAL`
- `basic.overall` enum: `ACTIVE_FULL`, `ACTIVE_PARTIAL`, `DEGRADED_PARTIAL`, `DEGRADED`, `MISSING_OUTPUT`

## Tests Enforcing This Contract

| Test | File | Line | Asserts |
|------|------|------|---------|
| `test_active_path_no_x_pre_x_realized_voting` | `test_canonical_runtime_contracts.py` | 45 | No X_PRE/X_REALIZED as canonical_voting |
| `test_framework_output_schema_valid` | `test_canonical_runtime_contracts.py` | 62 | framework_output conforms to schema |
| `test_framework_output_has_quality_status` | `test_canonical_runtime_contracts.py` | 87 | quality_status present and valid |
| `test_framework_output_sigma_vector_has_x_agg` | `test_canonical_runtime_contracts.py` | 103 | SigmaVector includes X_agg |
| `test_readme_shows_output_source` | `test_canonical_runtime_contracts.py` | 117 | README shows structural_replay_v2 source |
| `test_readme_shows_quality_status` | `test_canonical_runtime_contracts.py` | 133 | README displays quality status |
| `test_k_voting_proxies_are_options_derived` | `test_canonical_runtime_contracts.py` | 146 | K proxies exist with canonical_voting |
| `test_x_agg_has_canonical_voting_proxies` | `test_canonical_runtime_contracts.py` | 159 | X_agg has canonical_voting proxies |
