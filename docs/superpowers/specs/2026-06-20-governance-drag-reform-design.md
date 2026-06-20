# Governance Drag Reform Design

**Date:** 2026-06-20
**Status:** Approved
**Scope:** Enhance existing drag report + incentive engine penalty. No new governance files.

---

## Problem Statement

The system has entered "Governance Capture" — the governance layer is self-replicating. Agent work increasingly serves governance maintenance (hash reconcile, registry sync, baseline update) rather than system capability improvement. The existing drag report and incentive penalty are present but shallow.

**Diagnosis:** 40% of recent commits are governance-related. 32 governance YAML files. 57 scripts without tests. The freeze hash reconciliation happened 3 times in 4 days (27 approved hash transitions).

## Decision

Enhance two existing files in-place. No new files, no new governance layers.

1. **`scripts/build_governance_drag_report.py`** — upgrade from v1 to v2 with deeper metrics
2. **`scripts/_incentive_engine.py`** — enhance `_load_drag_penalty()` with governance ratio penalty and non-action bonus

Freeze severity reform is already complete (baseline_file_modified is severity: medium).

---

## Component 1: Enhanced Drag Report (`build_governance_drag_report.py`)

### Schema: `governance_drag_report.v2`

### Existing 8 metrics (keep, enhance 4)

| # | Metric | v1 | v2 |
|---|--------|----|----|
| 1 | `daily_active_step_count` | 23 | unchanged |
| 2 | `root_script_count` | 83 | unchanged |
| 3 | `governance_file_count` | 32 | unchanged |
| 4 | `registry_entry_count` | 0 (only module_authority_registry) | **count active entries across all 14 registries** |
| 5 | `script_without_test_count` | 57 | unchanged |
| 6 | `orphan_output_count` | 1 | unchanged |
| 7 | `hash_reconcile_commits_last_10` | 0 | **also read baseline_updates from manifest** |
| 8 | `governance_commits_ratio_last_10` | 0.4 (binary) | **5-class classification** |

### New 3 metrics

| # | Metric | Calculation |
|---|--------|-------------|
| 9 | `orphan_registry_entries` | active entrypoint_registry entries with no corresponding script in scripts/ |
| 10 | `non_action_count` | capability_registry entries with status PAPER_RETAIN, BLOCKED, or REAL_EXPERIMENTAL+blockers |
| 11 | `active_daily_vs_weekly_ratio` | daily_count / weekly_count (lower = better) |

### Enhanced `_count_registry_entries()`

Iterate all `governance/*_registry.yaml` and `governance/*_registry.json`. For each:
- Load YAML/JSON
- Count entries that are NOT archived/disabled/deprecated
- "Active" means: entry has no `status` field, OR status is not in {"archived", "disabled", "deprecated", "shadow_active"}
- For registries with list-of-dicts structure (operator_registry, module_authority_registry): iterate list, filter by status
- For registries with dict-of-dicts structure (entrypoint_registry, capability_registry): iterate values, filter by status
- For registries with no entry-level status field: count all entries
- Sum across all registries

Registries to cover (14):
- entrypoint_registry, daily_pipeline_registry, operator_registry, semantic_registry
- capability_registry, module_authority_registry, data_authority_registry
- experimental_submission_registry, config_authority_registry, data_request_registry
- run_mode_registry, module_contract_registry, authority_graph_policy
- governance_freeze_manifest

### Enhanced `_governance_commits_ratio()`

5-class classification with independent keyword sets:

| Class | Keywords | Meaning |
|-------|----------|---------|
| capability | signal, judgment, trade, harvester, bridge, replay, measurement, regime | Real capability increase |
| validation | test, baseline, verify, check, assert, coverage, invariant | Real test/verification |
| simplification | archive, remove, delete, merge, simplify, downgrade, slim, retire | Deletion/archival/downgrade |
| governance_sync | hash, reconcile, freeze, registry, baseline_update, manifest | Governance synchronization |
| cosmetic_governance | policy, schema, format, comment, wording, metadata | Surface governance |

Output:
```json
"commit_classification": {
  "capability": 0.2,
  "validation": 0.1,
  "simplification": 0.1,
  "governance_sync": 0.3,
  "cosmetic_governance": 0.1,
  "unclassified": 0.2
}
```

### Enhanced `_count_hash_reconcile_commits()`

Read `governance_freeze_manifest.yaml` `baseline_updates` list. Count total approved hash transitions. Take max(git_log_count, manifest_count).

### New `_count_orphan_registry_entries()`

For each active entry in entrypoint_registry:
- Check if `scripts/{entry_id}.py` or `scripts/{entry_id}` exists
- If not, it's an orphan

### New `_count_non_action()`

Read capability_registry.yaml. Count entries where:
- status == "PAPER_RETAIN"
- status == "BLOCKED"
- status == "REAL_EXPERIMENTAL" AND blockers is non-empty

### New `_daily_vs_weekly_ratio()`

`daily_count / weekly_count` from daily_run_sequence.yaml.

### Enhanced recommendations

New output fields:
```json
{
  "recommendations": ["..."],
  "top_drag_sources": [
    {"component": "governance_file_drag", "score": 8.5, "detail": "32 governance YAMLs"}
  ],
  "daily_to_weekly_candidates": [
    {"step_id": "market_feedback", "reason": "validation-only, not consumed by signal chain"}
  ],
  "archive_candidates": [
    {"file": "module_contract_registry.yaml", "reason": "only 1 test consumer"}
  ]
}
```

`daily_to_weekly_candidates`: daily steps where `allowed_to_affect_core_judgment: false` AND failure_behavior is `continue_with_warning`.

`archive_candidates`: governance YAML files with no production script consumer.

### Drag score formula update

Existing 8 component scores keep their formulas. New components:

| Component | Threshold | Formula |
|-----------|-----------|---------|
| `orphan_registry_drag` | 5=0, 20=10 | min(10, max(0, (count-5)/1.5)) |
| `non_action_drag` | reversed: more non-action = LESS drag | min(10, max(0, 10 - count)) |
| `daily_weekly_ratio_drag` | 1.0=0, 0.3=10 | min(10, max(0, (1.0-ratio)*14.3)) |

`non_action_drag` is inverted: having more archived/deferred modules REDUCES drag score. This rewards correct non-action.

---

## Component 2: Enhanced Incentive Penalty (`_incentive_engine.py`)

### Function: `_load_drag_penalty(root)`

**Current:**
```python
penalty = min(5, int(total_drag / 10))
```

**New:**
```python
base_penalty = min(5, int(total_drag / 10))

# Governance ratio extra penalty
gov_ratio = metrics.get("governance_commits_ratio_last_10", 0)
gov_penalty = min(2, max(0, int((gov_ratio - 0.4) * 10)))

# Non-action bonus (rewards correct non-action)
non_action = metrics.get("non_action_count", 0)
non_action_bonus = min(2, non_action // 3)

final_penalty = max(0, base_penalty + gov_penalty - non_action_bonus)
```

### Return value change

```python
{
    "penalty": final_penalty,           # used by compute_credit_score
    "base_penalty": base_penalty,       # from total_drag_score
    "gov_penalty": gov_penalty,         # governance ratio penalty
    "non_action_bonus": non_action_bonus, # non-action reward
    "drag_score": total_drag,
    "severity": severity,
    "source": "governance_drag_report",
    "components": component_scores,
}
```

### Schema upgrade

`incentive_review.v3` → `incentive_review.v4`. The `complexity_penalty` field gains sub-fields `base_penalty`, `gov_penalty`, `non_action_bonus`.

### Test impact

`tests/test_incentive_engine.py` needs updated mock `governance_drag_report.json` with v2 fields. The `_load_drag_penalty` return value structure changes.

---

## What We Are NOT Doing

- No new YAML files in governance/
- No new registry entries
- No new pipeline steps
- No new scripts
- No changes to `_governance_freeze.py` (already done)
- No changes to authority graph logic
- No changes to daily_run.py

## Success Criteria

1. `governance_drag_report.json` v2 produces accurate metrics across all 14 registries
2. Commit classification produces 5-category breakdown
3. `non_action_count` correctly identifies archived/blocked/experimental modules
4. Incentive penalty reflects governance ratio and rewards non-action
5. All existing tests pass (with updated mocks)
6. No new governance files created

## Files Modified

| File | Change |
|------|--------|
| `scripts/build_governance_drag_report.py` | Enhance metrics, add new indicators |
| `scripts/_incentive_engine.py` | Enhance `_load_drag_penalty()` |
| `tests/test_incentive_engine.py` | Update mocks for v2 drag report |
