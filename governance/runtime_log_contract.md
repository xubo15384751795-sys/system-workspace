# Runtime Log Contract

**Owner:** `system-learning-hub/` (System Learning Hub)  
**Status:** active (2026-05-22)

## Principle

Governance memory is **recorded in one place**. Peer modules (Workbench,
Harvester, Deformation, harness) must **not** embed their own learning sensors
or write directly into `Data/system_learning/` or scattered event files.

| Role | Allowed | Forbidden |
|---|---|---|
| **Learning Hub** | append runtime records, derive ledgers, write reports | modify peer module code or canonical data |
| **Peer modules** | read Hub runtime log + latest reports | write `Output/system_learning/events/`, per-module `system_events.jsonl`, or ledger Parquet |

Recording may be implemented as append-only **runtime logs** under Hub control.

## Canonical paths

```text
Output/system_learning/runtime/records_YYYY-MM-DD.jsonl   # append-only runtime log (Hub writes)
Data/system_learning/ledgers/                             # derived ledgers (Hub writes)
Output/system_learning/latest/                            # human reports (Hub writes)
```

Peer modules consume:

```text
Output/system_learning/latest/summary.json
Output/system_learning/latest/*.md
Output/system_learning/runtime/records_*.jsonl            # read-only tail / scan
Data/system_learning/ledgers/*.parquet                    # read-only query
```

## How peer modules record an observation

Do **not** open runtime log files directly. Use the Hub entrypoint:

```bash
PYTHONPATH=system-learning-hub/src python3 -m system_learning record \
  --system-root /Users/a1/System \
  --subsystem workbench \
  --event-type snapshot_publish_attempt \
  --severity error \
  --payload-json '{"decision":"deny","run_id":"..."}'
```

Or the workspace wrapper:

```bash
python3 scripts/record_runtime_event.py --subsystem harness --event-type tool_run --payload-json '...'
```

Hub normalizes each line to `system_event.v1` during append.

## How peer modules read runtime state

1. Read `Output/system_learning/latest/summary.json` for the current digest.
2. Tail `Output/system_learning/runtime/records_*.jsonl` when raw chronology is needed.
3. Never treat `Workbench/Output/system_learning/` or `system-learning-hub/data/` as truth.

## Deprecated patterns (migration in progress)

These are **legacy sensor outputs** — do not add new writers:

- `Workbench/agents/harness/events/system_event_writer.py` direct file append
- `Output/system_learning/events/events_*.jsonl` from non-Hub code
- `Output/deformation_runs/*/system_events.jsonl` as peer emitters
- `Data/harvester/exports/*/system_events.jsonl` as peer emitters
- `Workbench/Output/system_learning/verifications/`

Hub may still **ingest legacy files** during transition, but new instrumentation
must go through `system_learning record` only.

## Internal Hub scans (not peer sensors)

Codebase cartography and ML integrity checks run **inside** Learning Hub (`scan-codebase`,
`check-ml-integrity`). They are Hub-owned recorders, not module-embedded sensors.
