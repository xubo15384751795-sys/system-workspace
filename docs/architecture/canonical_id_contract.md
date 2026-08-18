# Canonical ID / schema contract

## Purpose

The runtime chain is now represented as four explicit objects:

```text
Observation -> Measurement -> Evidence -> Claim
```

The machine-readable contract is [`protocols/canonical_chain.schema.json`](../../protocols/canonical_chain.schema.json), and the constructors/validator live in [`system_runtime/canonical_ids.py`](../../system_runtime/canonical_ids.py).

## ID rules

Each ID is a deterministic SHA-256 digest over normalized identity fields. The
digest is shortened to 128 bits and namespaced by object type:

| Object | Prefix | Identity includes | Volatile fields excluded |
| --- | --- | --- | --- |
| Observation | `obs_` | canonical series, observed/vintage time, value, scope, status, source and snapshot hash | run ID, generated time, parser logs |
| Measurement | `mea_` | sorted observation IDs, definition, method version, status and derivation | run ID, generated time |
| Evidence | `evd_` | sorted measurement IDs, role, source, release and snapshot hash | run ID, generated time |
| Claim | `clm_` | normalized proposition, subject, predicate and policy version | current evidence set, run ID |

The claim rule is intentional: new evidence changes the claim's links and
status, not the identity of the proposition itself. A retry over the same
source snapshot therefore remains idempotent.

## State semantics

Missingness is explicit rather than collapsed into `null`:

`AVAILABLE`, `STALE`, `DELAYED`, `MISSING`, `NOT_APPLICABLE`, `SOURCE_DOWN`,
`SCHEMA_CHANGED`, `DISCONTINUED`, and `UNKNOWN`.

Measurement derivation is separate from availability:

`OBSERVED`, `ESTIMATED`, `INTERPOLATED`, `MODELED`, `PROXY_DERIVED`,
`ASSUMED`, and `NOT_OBSERVABLE`.

Claim status is deliberately non-binary:

`SUPPORTED`, `WEAKLY_SUPPORTED`, `CONFLICTED`, `STALE`, `INSUFFICIENT_DATA`,
`UNOBSERVABLE`, and `WATCH`.

## Compatibility and migration boundary

This phase does not migrate orchestration. Existing output fields remain in
place, including the legacy `macro_pressure_measurement` and public `C005`
label. New consumers can read `canonical_chain` or the compact
`canonical_ids` block. The neutral pressure producer now emits a fully
validated chain, and Workbench NLP chunk evidence IDs use the canonical
`evd_` generator. New Claim Ladder state entries use canonical `clm_` IDs and
retain the old slug as `legacy_claim_id`.

The next migration phase may replace legacy fields only after every reader has
passed the parity fixture and the default scheduled path has been verified.
The current-schema CI validator also re-runs the cross-object validator whenever
an output contains `canonical_chain`; a permissive legacy envelope cannot
silently bypass the contract.

The orchestration migration now has a bounded shadow comparator in
`packages/orchestration/orchestration/shadow_parity.py`. It compares already
executed Dagster/direct result lists using deterministic step semantics and,
when present, all four canonical IDs. Matching execution without canonical IDs
is reported as `EXECUTION_MATCH_CANONICAL_UNAVAILABLE`, not as a migration
pass. The report is always `shadow_only` with `promotion_allowed=false`; it does
not execute a second production path or change the scheduler's authority.

The executor now has a read-only bridge in
`packages/orchestration/orchestration/canonical_lineage.py`. After a successful
step it inspects only the step's declared JSON outputs, resolves the active
candidate surface (including generation mode), requires the output `run_id` to
match the current bundle, and runs the canonical-chain validator before adding
`canonical_chain` / `canonical_ids` to the step result. Failed steps, stale
outputs, invalid envelopes, and unstamped runs are ignored. This is the first
shadow-path lineage feed; it does not create IDs, publish, or switch readers.
The daily `RunBundle` recorder carries these fields into `steps.jsonl` as
additive provenance. `system_runtime.canonical_lineage.summarize_step_lineage`
now gives the alert, operator-event, and notification readers a shared
shadow-only dual-read context. It revalidates the chain and checks the compact
four-ID block before reporting `MATCH` or `PARITY_MISMATCH`; missing lineage is
reported as `UNAVAILABLE`. PublishTransaction, Current, and admission still
use their existing run/release/generation contracts. The admission token and
minimum-monitoring publication reader may carry/report the same context, but a
canonical Claim cannot grant authority merely because its IDs are present in a
step log, and a reader-level mismatch is diagnostic rather than an automatic
publish block.

## Harvester producer boundary (SYS-18)

Harvester producers now emit an Observation-only sidecar for the cross-asset
ETF release at
`provenance/cross_asset_daily_panel.canonical_observations.jsonl`. Each record
uses the existing `obs_` constructor and links back to the accepted release
hash. Provider fallback metadata remains provenance-side: every ETF series may
carry a `provider_attempt_id` (`att_...`), attempt number, source tier, outcome,
and retryability in `provider_outcome.series_attempts`.

This is intentionally not a fifth canonical-chain object and does not change
the four frozen ID rules. Measurement, Evidence, and Claim records will consume
these observations in the later producer migration; until then, the sidecar
path and count are declared in the Harvester provenance contract and validated
at release finalization.

The next additive slice now also emits
`provenance/cross_asset_daily_panel.canonical_chains.jsonl`. Each line is a
fully validated Observation -> Measurement -> Evidence -> Claim envelope for
one ETF close. The Claim is explicitly a `recorded_observation` statement with
`claim_ceiling=diagnostic_observation_only`, `promotion_allowed=false`, and
`WATCH`/`STALE` status; it is not a market or portfolio judgment. Finalization
checks the sidecar path, JSONL validity, canonical IDs, cross-object links, and
declared record count. The original Observation-only sidecar and all legacy
release fields remain unchanged.

The official long panel now uses the same bounded helper and writes matching
`official_panel.canonical_observations.jsonl` and
`official_panel.canonical_chains.jsonl` sidecars. Provider attempts and
carry-forward status remain in provenance; a missing value stays `MISSING`
instead of being coerced into a zero or a fresh observation.

Provider attempts now also carry a stable `failure_class` alongside the
legacy `reason`: `NONE`, `NO_DATA`, `PROVIDER_DOWN`, `NETWORK`,
`SCHEMA_CHANGED`, `PARSER`, `PERMISSION`, `RATE_LIMIT`, or `UNKNOWN`.
The ETF chain emits this field for every attempt, and selected observations
copy it into provenance. This keeps provider-specific wording out of
admission logic while preserving the original reason and `att_` identity. The
Harvester promotion gate reads the normalized failed-attempt classes, exposes
them in `gate_report.json`, and rejects an unrecognized class; valid classes
remain diagnostic metadata and do not silently override the existing provider
status policy.

The derived `proxy_candidate_panel` is deliberately different. It writes
`provenance/proxy_candidate_panel.measurement_spec.json`, validated by
`packages/harvester/contracts/proxy_measurement_spec.schema.json`, rather than
an Observation -> Measurement -> Evidence -> Claim sidecar. The spec records
`PROXY_DERIVED`, the input source ladder, recognized missingness states, and the
rules that prohibit imputation and carry-forward. Its ceiling is
`diagnostic_proxy_candidate_only` and `promotion_allowed=false`. A proxy can
enter the canonical research chain only after a target-specific MeasurementSpec
defines the proxy-to-target relationship, conflict/uncertainty handling, and an
explicit human-reviewed promotion gate.

## Claim Ladder producer boundary (SYS-18)

Claim Ladder state now keeps the legacy workflow fields and adds a standalone
`canonical_claim` plus `canonical_claim_id`. The claim is validated with the
same deterministic `clm_` identity rules, while `evidence_ids` remains empty
unless an evidence writer has supplied real `evd_` references. Therefore every
new ladder entry is explicitly `WATCH` with `claim_ceiling=diagnostic_watch_only`;
promotion in the workflow cannot silently become publication authority. An
invalidated ladder entry is represented as canonical `CONFLICTED` while its
legacy status remains `invalidated` for compatibility.

The Workbench C005 historical morphology report follows the same boundary. It
retains the legacy `C005` field and adds a standalone canonical claim, but keeps
`evidence_ids=[]`, `historical_evidence_only=true`, and
`promotion_allowed=false` until the underlying benchmark/residual artifacts
are promoted to first-class evidence records. A populated report therefore
does not silently become a current publishable claim.

Workbench NLP answer citations retain content-stable `evd_`-prefixed IDs for
retrieval and path-move stability, but declare `evidence_kind=RETRIEVAL_CITATION`,
`canonical_evidence=false`, and `promotion_allowed=false`. They are references
to text chunks used by the answering operator, not canonical Evidence objects:
there is no Measurement link and they cannot be consumed as current research
evidence without a separate, validated writer.

The neutral-pressure producer follows the same conservative boundary. Its
canonical Claim is bounded measurement metadata rather than a universal
research judgment: it declares `statement_kind=bounded_neutral_measurement`,
`claim_ceiling=bounded_neutral_measurement`, and `promotion_allowed=false`.
The legacy snapshot fields remain unchanged for compatibility.

## Workbench NLP event-card boundary (SYS-18)

Structural NLP event cards now carry an additive `canonical_claim_id` and
`canonical_claim` when written by the event-card exporter or promotion flow.
The claim uses the stable `clm_` identity but remains `WATCH` for candidate,
reviewed, canonical, and admitted legacy statuses; rejected and needs-revision
cards are represented as `CONFLICTED`. In all cases the claim has
`claim_ceiling=diagnostic_watch_only`, `promotion_allowed=false`, and an empty
`evidence_ids` list. A source quote is therefore traceable without being
silently promoted to canonical Evidence. The candidate ledger records the
claim ID, status, ceiling, and empty canonical evidence list for replay and
parity checks.
Rejected and needs-revision hard-case records carry the same diagnostic Claim
lineage, mapped to `CONFLICTED`, so error-mining remains traceable without
turning a negative training example into publishable evidence.

## Framework runtime evidence boundary (SYS-18)

`RuntimeEvidenceStore.build_snapshot_bundle()` now exposes an additive
`canonical_chain` through the runtime API. The bundle is a computed feature
summary, so its Measurement is `PROXY_DERIVED`, its Evidence role is `DERIVED`,
and its Claim is `diagnostic_evidence_bundle` with
`claim_ceiling=diagnostic_watch_only` and `promotion_allowed=false`. Mock input
is represented as `MISSING` and degraded input as `STALE`; neither state can be
silently promoted. Existing `families` and metadata payloads remain unchanged.

CaseLab event resolution follows the same candidate boundary. Resolver output
now carries a validated standalone Claim with empty `evidence_ids`,
`statement_kind=diagnostic_event_resolution`, and
`evidence_boundary=case_context_and_rule_output_not_canonical_evidence`.
Entity context, rule-based impact, and historical precedent remain discovery
artifacts; they cannot become current Evidence or a promoted judgment without a
separate observation and measurement writer.

The CaseLab `case_library` is an even earlier historical-reference layer. Each
`CaseProfile` is now marked `artifact_class=historical_case_profile` with
`claim_ceiling=historical_reference_only` and `promotion_allowed=false`; the
model rejects attempts to load a current-evidence or promotable case profile.
Similarity and precedent consumers can continue reading the legacy vector and
narrative fields, but a case profile must be re-measured through a fresh
Observation/Measurement writer before it can participate in a current claim.

## Acceptance criteria

1. The parity fixture validates against the JSON Schema and all three cross-object links.
2. Re-running a producer over unchanged input yields the same four IDs.
3. Changing an observation value changes observation and measurement IDs while keeping the proposition's claim ID stable.
4. A broken observation -> measurement -> evidence -> claim link fails validation.
5. Existing framework-output validation remains green with the optional canonical envelope present.
6. A proxy candidate without a valid measurement specification fails release finalization;
   a valid proxy spec still cannot authorize promotion.
7. Orchestration shadow comparison reports execution parity separately from
   canonical-lineage parity and never grants publish authority.
8. A current-run, validator-approved declared output can move shadow status to
   canonical-lineage `MATCH`; a prior-run or failed-step output cannot.
9. Alert/operator/notification readers expose the same shadow-only lineage
   context, while publish/current/admission verdicts remain unchanged when
   canonical lineage is missing or mismatched.
