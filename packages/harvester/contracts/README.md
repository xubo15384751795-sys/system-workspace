# Harvester Contracts

**Status: FROZEN as of 2026-04-26.**
**Schema family version: 1.0.**

Contracts are frozen specs. Code in `src/` must conform to contracts.
Contract changes require an explicit version bump and migration plan
(see `access_protocol.md` §7).

## Files

- `access_protocol.md` — boundary statement, on-disk layout, scope,
  release identifiers, immutability rules, time semantics, schema
  versioning, integrity verification, failure modes. **FROZEN
  2026-04-26, §12 clarifications appended same day** (explanatory,
  no normative change, no version bump).
- `catalog.schema.json` — JSON Schema (Draft 2020-12) for the per-release
  `catalog.json` index file.
- `dataset_manifest.schema.json` — JSON Schema (Draft 2020-12) for one
  dataset's `<dataset_id>.manifest.json`.
- `provenance.schema.json` — JSON Schema (Draft 2020-12) for one dataset's
  `<dataset_id>.provenance.json`.

A `quality_report.schema.json` is referenced by `access_protocol.md` §11
as future work; it is intentionally out of scope for the 1.0 freeze.

## Validation

All three schemas have been meta-validated against the Draft 2020-12
meta-schema and cross-checked for consistent regex patterns on
`release_id`, `dataset_id`, `sha256`, `schema_version`, and the
relative-path families.
