# Learning Hub Context

Learning Hub is the **sole recorder** of workspace governance memory. Peer
modules must not embed learning sensors or write learning artifacts directly.

## Owns

- runtime log append (`Output/system_learning/runtime/`)
- ledger derivation (`Data/system_learning/ledgers/`)
- governance reports (`Output/system_learning/latest/`)
- architecture drift records (via Hub-internal scans)
- boundary violation recurrence analysis
- routing decision copies (read from workspace; indexed by Hub)
- improvement queue lifecycle
- NLP hard-case indexing (from NLP library exports)

## Primary Paths

- `packages/learning_hub/` — canonical source in the workspace monorepo
- `System Learning Hub/` — compatibility symlink to `packages/learning_hub/`
- `Data/system_learning/` — canonical ledgers and registries
- `Output/system_learning/runtime/` — append-only runtime log (**Hub writes**)
- `Output/system_learning/latest/` — derived reports (**Hub writes**)
- `governance/runtime_log_contract.md` — write/read contract for all modules

## Peer module obligations

**Record:** call `python3 scripts/record_runtime_event.py` or
`python3 -m system_learning record` — never open runtime log files directly.
Daily runs also dual-write via `scripts/record_daily_run_event.py` →
`append_runtime_record` (`Output/system_learning/runtime/records_*.jsonl`).
Ingest collectors also read `<<KEEP_STATE_{name}>>_events/*.jsonl`.

**Read:** consume `Output/system_learning/latest/summary.json` and runtime log /
ledger outputs. Treat Hub records as the authoritative governance chronology.

### Not workspace truth

- `Workbench/Output/system_learning/` — removed (was legacy scratch; not workspace truth)
- `Output/system_learning/events/` — legacy sensor output (deprecated)
- `system-learning-hub/data/` — repo-local fixtures only

## Reads

- runtime log and legacy ingest paths during migration
- routing decisions under `Output/system_learning/routing_decisions/`
- governance checkpoints under `.cursor/checkpoints/`
- `governance/open_threads.yaml` as a migration-only input; the Hub improvement
  queue is the sole live work queue
- NLP candidate ledgers when NLP governance is involved
- operational artifacts (run manifests, releases) for Hub-internal scans only

## Writes

- runtime log records (via Hub `record` API only)
- derived ledgers and reports (via Hub pipeline only)

## Promises

- We keep runtime records append-only and derived reports reproducible from their sources.
- Credit changes review priority only; it never changes permission or promotion authority.
- We report deviations only and raise zero monthly hypothesis inflow as a monitoring failure.

## Relies On

- Peer modules promise to use the Hub record API instead of writing ledgers directly.
- Routing decisions promise bounded scope, observation windows and rollback for complex probes.
- The selector promises never to treat `hypotheses_inbox.md` as evidence or a claim source.

## Must Not

- allow peer modules to append learning events directly
- silently promote exploratory work
- replace Framework claims, Workbench behavior, or Harvester evidence
- treat audit findings as production inputs

## Read First

- `MODULES.md`
- this file
- `governance/runtime_log_contract.md`
- `governance/repo_layout_map.md` §4
- `ROUTING_CONSTITUTION.md`

## Escalate When

- a module needs a new runtime record shape
- a peer module still writes to deprecated event paths
- a governance record requires code changes outside Hub ingest

Escalation usually goes to the owner module plus `protocols.md` if the handoff
shape changes.
