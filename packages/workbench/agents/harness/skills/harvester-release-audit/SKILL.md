# Harvester Release Audit

## Trigger
When a Harvester data release is created, published, consumed by Deformation, or cited in a paper.
Also triggered before any `harvester.list_releases`, `harvester.inspect_release`, or `harvester.diff_releases` invocation in verify/release modes.

## Scope
- Harvester release catalog integrity (catalog.json, bundle_id, created_at)
- File existence and count consistency
- Schema conformance (required top-level keys)
- Hash verification of release artifacts
- Finalized release immutability enforcement
- Provider provenance (FRED, SEC, fallback detection)

## Read First
- `Data/harvester/exports/<release_id>/catalog.json`
- `Data/harvester/exports/<release_id>/` — complete file listing
- `Structural Risk Harvester/contracts/access_protocol.md`
- `policies/boundary_rules.yaml` — rules `boundary.deny.finalized-release-immutable`
- `policies/feature_flags.yaml` — `harvester.simulated_data_fallback: denied_for_release`
- Previous release catalog for diff baseline

## Steps

### Step 1: Inventory
```
system tools run harvester.list_releases --mode explore --json
```
Collect all release IDs, created_at timestamps, file counts.

### Step 2: Inspect Target Release
```
system tools run harvester.inspect_release --mode explore release_id=<ID> --json
```
Extract: catalog.json structure, bundle_id, created_at, file list with paths/format/row_count/byte_size.

### Step 3: Verify Release Integrity
```
system tools run harvester.verify_release --mode verify release_id=<ID> --json
```
Run automated integrity checks:
- Catalog JSON parseable
- Required keys present (bundle_id, created_at, files)
- All listed files exist on disk
- File sizes match catalog entries

### Step 4: Diff Against Previous Release
```
system tools run harvester.diff_releases --mode explore release_a=<PREV_ID> release_b=<ID> --json
```
Identify: files added, files removed, files common, count drift.

### Step 5: Provider Provenance Audit
For each release, verify:
- No `harvester.simulated_data_fallback` in release context
- `harvester.fred_provider` and `harvester.sec_provider` correctly tagged as `engineering_required`
- Data source path is from official exports, not raw/processed/corpus

## Required Evidence
- [ ] Release inventory (all release IDs, timestamps)
- [ ] Target release catalog (full JSON)
- [ ] Integrity check results (pass/fail per check with detail)
- [ ] Diff report (added/removed/common file lists)
- [ ] Provider provenance assessment
- [ ] Feature gate compliance report (simulated_data_fallback check)
- [ ] Audit timestamp and auditor identity

## Forbidden
- Modifying a finalized release (immutable — `boundary.deny.finalized-release-immutable`)
- Writing to `Data/harvester/raw/`, `Data/harvester/processed/`, `Data/harvester/corpus/`
- Promoting `harvester.simulated_data_fallback` into any release output
- Releasing FRED/SEC provider data as `paper_aligned` without engineering review
- Encoding Deformation theory into Harvester catalog semantics

## Output Artifact
```json
{
  "audit_id": "harvester-release-audit-<date>-<release_id>",
  "audit_type": "harvester_release",
  "target_release": "<release_id>",
  "verdict": "PASS | FAIL | PARTIAL",
  "evidence": {
    "inventory": [...],
    "catalog": {...},
    "integrity_checks": [...],
    "diff": {...},
    "provenance": {...}
  },
  "blockers": [],
  "residual_risks": [],
  "output_path": "Output/system_learning/audits/harvester-release-<id>.json"
}
```
