# HANDOFF - Structural Deformation Research System

Last updated: 2026-04-20
Workspace: `/Users/a1/System/Structural Deformation Research System`

## Current Shape

The project has been consolidated into a package-first structure:

- `src/core`: contracts, dataclasses, pipeline orchestration, provenance
- `src/data`: data-source adapters and DuckDB snapshot storage
- `src/derivation`: proxy construction, graph engine, singular diagnostics
- `src/dynamics`: ODE evolution engine
- `src/mechanisms`: literature mechanisms coarse-grained to `M/D/K/X`
- `src/operators`: structural event-as-operator algebra
- `src/benchmarks`: comparator stress indicators and historical replay tools
- `src/simulation`: scenario and phase-diagram lab
- `src/ml`: optional anomaly, narrative, and reflexivity detectors
- `src/output`: JSON/HTML/PNG export
- `ui`: Streamlit runtime, components, and task pages

The old root-level modules (`interfaces.py`, `pipeline.py`, `modules/*`) were replaced by the `src/` package and should stay removed.

## Structural Operator Layer

Events are represented as state-dependent operators over `M/D/K/X`, then composed in event-log order before ODE integration:

```text
raw data -> proxy M/D/K/X -> event operator sequence -> ODE dynamics -> singular/reflexivity/narrative checks
```

Important files:

- `src/operators/operator_schema.py`
- `src/operators/operator_registry.py`
- `src/operators/operator_algebra.py`
- `src/operators/operator_diagnostics.py`
- `src/operators/event_to_operator.py`

Snapshot payloads include `state.operator_diagnostics`, such as `sequence_signature`, `compression_ratio`, `non_commutativity_score`, and `singular_proximity`.

## UI Constraints

The Streamlit UI should remain a readout layer:

- Allowed: `pipeline.run()` and `snapshot_store.load()/load_range()`
- Avoid importing proxy builders, ODE engines, or detector internals directly in UI pages
- Event-log writes should flow through `EventLogger`
- Generated data belongs in ignored runtime paths (`data/`, `output/`)

## Runtime

CLI:

```bash
python3 assembly.py
```

UI:

```bash
python3 -m streamlit run app.py --server.address 127.0.0.1 --server.port 8765
```

Tests:

```bash
python3 -m unittest discover -s tests
```

## Data Notes

`data/` and `output/` are ignored. Recreate them by running the CLI, UI, or historical replay script.

The 2008 Lehman replay can be regenerated from the benchmark utilities using FRED graph CSV data; do not commit generated DuckDB/parquet/csv output unless a future task explicitly asks for fixtures.
