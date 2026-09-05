# Archived v1 Snapshot Audit

## Trigger
When inspecting archived Deformation v1 evidence or falsification records.
Not a live release or publish gate. `deformation.run_snapshot` is permanently denied (`ARCHIVED_FALSIFIED`).
Mandatory when an archived snapshot contains `singular_flag=true`, `sigma_t > 0.9`, or `severity: critical`.

## Scope
- Snapshot schema validity (manifest keys, required fields)
- Proxy channel integrity (M, D, K, X values, directions, availability)
- State correctness (sigma_t, singular_flag, leading_channel, pattern)
- Operator trace noncommutativity evidence
- Provenance: which release was consumed, run_type, run_purpose
- Fallback detection (simulated fallback must not enter production)
- Detector wording (narrative_detector output must not be treated as empirical claim)

## Read First
- `Output/deformation_runs/<run_id>/run_manifest.json`
- `Output/deformation_runs/<run_id>/<run_date>_<run_type>.json` (snapshot JSON)
- `Output/deformation_runs/<run_id>/data/snapshot.json` (fallback path)
- `packages/workbench/agents/harness/policies/boundary_rules.yaml` — rules for benchmark/exploratory/fallback
- `packages/workbench/agents/harness/policies/feature_flags.yaml` — all `deformation.*` features are `archived_denied`
- `ROUTING_CONSTITUTION.md` — `benchmark_proxy_separation`, `deformation_downscope`

## Steps

### Step 1: Inspect Snapshot
```
system tools run deformation.inspect_snapshot --mode explore snapshot_id=<ID> --json
```
Extract: run_date, run_type, run_purpose, status, proxy channels (M/D/K/X with values, direction, available), sigma_t, singular_flag, singular_time, leading_channel, pattern, severity, interpretation summary.

### Step 2: Archive Replay Evaluation
```
system tools run deformation.evaluate_replay --mode verify snapshot_id=<ID> --json
```
Read-only checks against archived artifacts:
- Manifest has required keys (run_date, run_type, status)
- Snapshot JSON present
- Operator trace exists for historical evidence
- Canonical promotion remains denied

### Step 4: Feature Gate Audit
```python
from packages.workbench.agents.harness.policies.feature_flags import can_promote, explain_gate
features = {
    "deformation.operator_noncommutativity": "archived_denied",
    "deformation.shadow_maturity_profile": "archived_denied",
    "deformation.ode_diffrax": "archived_denied",
    "deformation.gnn_benchmark": "archived_denied",
    "deformation.narrative_detector": "archived_denied",
    "deformation.simulated_data_fallback": "archived_denied",
    "deformation.benchmark_dominance": "archived_denied",
}
for name, expected in features.items():
    result = can_promote(name, "paper/main_output")
    if not result.allowed:
        record_blocked(name, result)
```

### Step 5: Boundary Compliance Check
- Verify snapshot did not consume Harvester raw data (`boundary.deny.deformation-reads-harvester-raw`)
- If `run_purpose=benchmark`, verify not routed to live Sigma_t
- If `run_purpose=exploratory`, verify not writing to paper/main_output
- If `run_mode=simulated_fallback`, verify not in publication flow

## Required Evidence
- [ ] Snapshot inspection (proxy channels, state, interpretation)
- [ ] Schema validation results (check-level pass/fail)
- [ ] Operator trace evidence (length, coupling, noncommutativity)
- [ ] Feature gate audit (per-feature status and paper-output eligibility)
- [ ] Boundary compliance report (benchmark/exploratory/fallback checks)
- [ ] Detector wording assessment (narrative_detector not promoted as claim)
- [ ] Singular regime risk note (if sigma_t → 1)

## Forbidden
- Treating `narrative_detector` output as empirical claim language
- Executing `deformation.run_snapshot` (permanently denied)
- Treating archived v1 evidence as a live host or promotion source
- Routing benchmark runs into live Sigma_t without explicit approval
- Writing exploratory output to `paper/main_output` or `paper/final`
- Reading Harvester raw/processed/corpus data directly
- Modifying the snapshot JSON during audit (read-only)

## Output Artifact
```json
{
  "audit_id": "deformation-snapshot-audit-<date>-<run_id>",
  "audit_type": "deformation_snapshot",
  "target_run": "<run_id>",
  "verdict": "PASS | FAIL | PARTIAL",
  "evidence": {
    "proxy": {"M": {...}, "D": {...}, "K": {...}, "X": {...}},
    "state": {"sigma_t": ..., "singular_flag": ..., "leading_channel": ...},
    "schema_checks": [...],
    "operator_trace": {...},
    "feature_gates": [...],
    "boundary_checks": [...]
  },
  "singular_regime_risk": "none | low | medium | high",
  "blockers": [],
  "residual_risks": [],
  "output_path": "Output/system_learning/audits/deformation-snapshot-<id>.json"
}
```
