# Test Results — Canonical Runtime + Status Hardening Sprint

**Date:** 2026-06-03  
**Sprint:** Canonical Runtime + Status Hardening  
**Status:** ✅ ALL PASS

## Summary

| Metric | Value |
|--------|-------|
| Total tests passing | **773** |
| New tests added | **8** |
| New test file | `tests/governance/test_canonical_runtime_contracts.py` |
| Test markers | `@pytest.mark.governance_loop`, `@pytest.mark.semantic` |

## New Canonical Runtime Contract Tests

All 8 tests in `tests/governance/test_canonical_runtime_contracts.py`:

| # | Test Name | Line | What It Enforces |
|---|-----------|------|------------------|
| 1 | `test_active_path_no_x_pre_x_realized_voting` | 45 | X_PRE/X_REALIZED must not have `canonical_voting` status — they are diagnostic only (Finance-2.tex §4.5) |
| 2 | `test_framework_output_schema_valid` | 62 | `framework_output.json` must have `schema_version == "workbench.framework_output.v2"`, required `basic` and `advanced` fields, valid `overall` enum |
| 3 | `test_framework_output_has_quality_status` | 87 | `basic.quality_status` must be present and one of `FULL_HIGH_CONFIDENCE`, `FULL_PROXY_REDUCED`, `FULL_WITH_WARNINGS`, `PARTIAL` |
| 4 | `test_framework_output_sigma_vector_has_x_agg` | 103 | `advanced.sigma_vector` must include `X_agg`, `channels_live`, and `complete` |
| 5 | `test_readme_shows_output_source` | 117 | `00_READ_ME_FIRST.md` must contain "Output source" and reference "structural_replay_v2" or "replay_bridge" |
| 6 | `test_readme_shows_quality_status` | 133 | `00_READ_ME_FIRST.md` must display "Quality:" status |
| 7 | `test_k_voting_proxies_are_options_derived` | 146 | K channel must have at least one `canonical_voting` proxy (§4.4 options-derived requirement) |
| 8 | `test_x_agg_has_canonical_voting_proxies` | 159 | X_agg channel must have at least one `canonical_voting` proxy |

## Test Infrastructure

- **Helper:** `_get_voting_proxies()` (line 22) — parses `scripts/structural_replay_v2.py` for `ProxySpec` blocks with `canonical_status`
- **Fixture paths:**
  - `FRAMEWORK_OUTPUT_PATH` = `ROOT/Output/current/framework_output.json`
  - `README_PATH` = `ROOT/Output/current/00_READ_ME_FIRST.md`
  - `REPLAY_SCRIPT` = `ROOT/scripts/structural_replay_v2.py`
- **Skip behavior:** Tests 2–6 skip gracefully if `framework_output.json` not found (run `bridge_replay_to_current.py` first)

## Test Run Command

```bash
# All governance tests
pytest tests/governance/ -v -m governance_loop

# Just the new contract tests
pytest tests/governance/test_canonical_runtime_contracts.py -v

# Full suite
pytest --tb=short  # 773 pass
```

## Enforcement Chain

These tests enforce the contracts documented in:
- `governance/audit-reports/CANONICAL_RUNTIME_CONTRACT.md`
- `governance/audit-reports/CURRENT_OUTPUT_PATH_DECISION.md`
- `governance/framework_output.schema.json`
