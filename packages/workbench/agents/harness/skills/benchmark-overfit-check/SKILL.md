# Archived Benchmark Overfit Audit

## Trigger
When auditing archived Deformation v1 benchmark evidence.
Not a live release or publish gate. `deformation.benchmark_dominance` is `archived_denied`.

## Scope
- No-lookahead validation (temporal alignment, release-date policy)
- Baseline rank evidence (NFCI, VIX, MOVE, STLFSI, OFR FSI controls)
- Ablation completeness (which proxy channels contribute)
- Incremental information evidence (does Sigma_t add beyond controls)
- Benchmark-to-proxy leakage (are benchmarks contaminating Sigma_t)
- Feature gate enforcement (`deformation.benchmark_dominance: archived_denied`)

## Read First
- `Output/deformation_runs/<run_id>/` — target snapshot and manifest
- `packages/workbench/agents/harness/policies/boundary_rules.yaml` — `boundary.deny.benchmark-silent-proxy-entry`
- `packages/workbench/agents/harness/policies/feature_flags.yaml` — `deformation.benchmark_dominance: archived_denied`
- `ROUTING_CONSTITUTION.md` — `benchmark_proxy_separation`
- Control data from finalized Harvester releases

## Steps

### Step 1: Identify Benchmark-Tagged Snapshots
Inspect snapshot manifest for `run_purpose=benchmark` or `run_type=benchmark`.
Separate benchmark runs from live proxy-core runs.

### Step 2: No-Lookahead Validation
- Verify release-date alignment: benchmark data timestamp < evaluation start timestamp
- Check training/evaluation split: no forward-looking information in training set
- Confirm frequency policy: benchmark uses same frequency as live deployment
- Evidence: timestamp comparison table, split boundary evidence

### Step 3: Baseline Rank Check
- List all control series used (NFCI, VIX, MOVE, STLFSI, OFR FSI)
- Compute baseline performance metrics (RMSE, rank correlation, hit rate)
- Compare Sigma_t performance against each baseline
- Check: is Sigma_t rank significantly different from baseline ranks?
- Evidence: baseline comparison table, statistical test results

### Step 4: Ablation Analysis
- Run deformation with individual proxy channels removed (M, D, K, X)
- Measure performance degradation per channel removal
- Check: does any single channel dominate?
- Evidence: ablation results table, channel contribution graph

### Step 5: Incremental Information Audit
- Compute baseline-only model performance
- Compute Sigma_t + baseline model performance
- Measure incremental improvement
- Check: is improvement statistically significant (p < 0.05, adjusted)?
- Evidence: incremental info table, significance test results

### Step 6: Feature Gate Compliance
```python
from packages.workbench.agents.harness.policies.feature_flags import can_promote, explain_gate
result = can_promote("deformation.benchmark_dominance", "paper/main_output")
assert not result.allowed  # archived_denied → no live output
print(explain_gate("deformation.benchmark_dominance", "paper/main_output"))
```

## Required Evidence
- [ ] No-lookahead validation (timestamps, split evidence)
- [ ] Baseline rank comparison (all controls, metrics, statistical tests)
- [ ] Ablation results (per-channel removal impact)
- [ ] Incremental information assessment (baseline vs Sigma_t + baseline)
- [ ] Benchmark-to-proxy leakage check (benchmark channels in operator trace)
- [ ] Feature gate compliance report
- [ ] Falsification risk note

## Forbidden
- Declaring "outperformance" without baseline rank evidence
- Claiming "dominance" from single run or case
- Routing benchmark sigma_t values into live proxy core
- Using forward-looking data in evaluation (no-lookahead violation)
- Treating archived `deformation.benchmark_dominance` as a live or paper-eligible feature
- Omitting baseline controls from comparison

## Output Artifact
```json
{
  "audit_id": "benchmark-overfit-<date>-<run_id>",
  "audit_type": "benchmark_overfit",
  "target_run": "<run_id>",
  "verdict": "PASS | FAIL | PARTIAL",
  "evidence": {
    "no_lookahead": {...},
    "baseline_rank": {...},
    "ablation": {...},
    "incremental_info": {...},
    "leakage_check": {...}
  },
  "benchmark_overfit_risk": "none | low | medium | high",
  "falsification_risks": [],
  "blockers": [],
  "residual_risks": [],
  "output_path": "Output/system_learning/audits/benchmark-overfit-<id>.json"
}
```
