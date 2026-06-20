# Framework Output Writer Consolidation Plan

**Date:** 2026-06-03  
**Sprint:** Canonical Runtime + Status Hardening  
**Status:** Plan — canonical writer designated

## Problem

7 writers produce `framework_output.json` (or equivalent). Risk of divergent schemas, stale data, and conflicting output sources.

## Writer Inventory

| # | Writer | Path | Role | Status |
|---|--------|------|------|--------|
| 1 | **bridge_replay_to_current.py** | `scripts/bridge_replay_to_current.py` | Canonical output writer | ✅ **CANONICAL** — produces `framework_output.json` + `00_READ_ME_FIRST.md` |
| 2 | current.py | `scripts/current.py` | Old Deformation run path | ⚠️ LEGACY — produces empty `{}` SigmaVector; output overwritten by bridge |
| 3 | openbb_secondary_audit.py | `scripts/openbb_secondary_audit.py` | OpenBB data audit | Module-specific output — does not write `framework_output.json` |
| 4 | nlp.py | `scripts/nlp.py` | NLP sentiment extraction | Module-specific output — paper capability only |
| 5 | workbench_tools.py | `scripts/workbench_tools.py` | Workbench utility functions | Module-specific output — helpers, not primary writer |
| 6 | test_canonical_runtime_contracts.py | `tests/governance/test_canonical_runtime_contracts.py` | Reads and validates output | ✅ Test — reads only, validates schema |
| 7 | test_framework_output.py (or similar) | `tests/` | Additional output validation | ✅ Test — reads only |

## Consolidation Rules

1. **`bridge_replay_to_current.py`** = single canonical writer for `Output/current/framework_output.json` and `Output/current/00_READ_ME_FIRST.md`
2. **`current.py`** = legacy. Still runs in `./sys refresh` before bridge (harmless — bridge overwrites). Do NOT remove yet — may have side artifacts.
3. **Module-specific writers** (openbb, nlp, workbench_tools) = write their own module output, NOT `framework_output.json`. No consolidation needed.
4. **Test writers** = read-only validation. No action needed.

## Enforcement Chain

```
./sys refresh
  → refresh_output_current.py (legacy, writes framework_output.json first)
  → bridge_replay_to_current.py (canonical, OVERWRITES framework_output.json)
  → build_artifact_navigator.py

./sys doctor
  → reads run_id from framework_output.json
  → warns if not replay_bridge_*
```

## Schema Reference

All writers of `framework_output.json` MUST conform to:  
**`governance/framework_output.schema.json`**

Key constraints:
- `schema_version` = `"workbench.framework_output.v2"`
- `run_id` must start with `"replay_bridge_"` for canonical path
- `basic` must contain: `overall`, `quality_status`, `main_pressure`, `confidence`, `summary`
- `advanced.sigma_vector` must contain: `M`, `D`, `K`, `X_agg`, `channels_live`, `channels_not_implemented`, `complete`, `dominant_channel`, `cofire_count`

## Future Actions

- [ ] Remove `current.py` from `./sys refresh` once confirmed no side artifacts are needed
- [ ] Add CI check: fail if `./sys doctor` warns about non-canonical source
- [ ] Add JSON schema validation step to `./sys refresh` post-bridge
