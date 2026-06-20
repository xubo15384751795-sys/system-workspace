# Current Output Path Decision

**Date:** 2026-06-03  
**Sprint:** Canonical Runtime + Status Hardening  
**Status:** DECIDED — enforce in CI

## Decision

`scripts/bridge_replay_to_current.py` is the **canonical output path** for `Output/current/`.

The old Deformation run path (`scripts/refresh_output_current.py` → `scripts/current.py`) is **legacy**. It still runs but its `framework_output.json` is overwritten by the bridge.

## Evidence

| Item | Detail |
|------|--------|
| Broken Deformation path | `scripts/current.py` produces `{}` in SigmaVector (see `governance/audit-reports/EXECUTION_REALITY_AUDIT_REPORT.md`) |
| Bridge path | `scripts/bridge_replay_to_current.py::build_framework_output()` (line 267) calls `build_sigma_vector()` from `workbench/governance.semantic` — produces correct 4-channel output |
| `./sys refresh` sequence | Line 10–11 of `sys`: runs `refresh_output_current.py` first, then `bridge_replay_to_current.py` — bridge overwrites stale output |
| `./sys doctor` check | Lines 82–96 of `sys`: reads `framework_output.json` `run_id`, checks for `replay_bridge` prefix, warns if not canonical |
| README stamp | `scripts/bridge_replay_to_current.py::write_readme()` (line 348) writes `Output source: structural_replay_v2 bridge (canonical)` into `00_READ_ME_FIRST.md` |
| Schema enforcement | `governance/framework_output.schema.json` requires `run_id` to start with `replay_bridge_` |

## How It Works

1. `./sys refresh` runs `refresh_output_current.py` (legacy, writes secondary artifacts)
2. `./sys refresh` then runs `bridge_replay_to_current.py` — **overwrites** `framework_output.json` and `00_READ_ME_FIRST.md` with canonical output
3. `./sys check` reads `00_READ_ME_FIRST.md` (lines 1–55) — always shows bridge output
4. `./sys doctor` reads `run_id` from `framework_output.json` and verifies `replay_bridge` prefix

## Key Functions

| Function | File | Line | Role |
|----------|------|------|------|
| `build_framework_output()` | `scripts/bridge_replay_to_current.py` | 267 | Builds canonical `framework_output.json` |
| `write_readme()` | `scripts/bridge_replay_to_current.py` | 348 | Generates `00_READ_ME_FIRST.md` with output source stamp |
| `main()` | `scripts/bridge_replay_to_current.py` | 457 | Entry point, writes both artifacts |
| `_load_sigma_vector()` | `scripts/bridge_replay_to_current.py` | 68 | Loads SigmaVector from replay engine |

## Enforcement

- Test: `tests/governance/test_canonical_runtime_contracts.py::test_readme_shows_output_source` — asserts `structural_replay_v2` in README
- Test: `tests/governance/test_canonical_runtime_contracts.py::test_framework_output_schema_valid` — asserts `schema_version == "workbench.framework_output.v2"`
- `./sys doctor` warns on non-canonical output source
