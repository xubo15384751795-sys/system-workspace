# Market Feedback Benchmark — Boundary Contract

## Qlib Role

Qlib is an **External Benchmark Executor** only. It is NOT:
- core system
- datahub
- harvester
- learning hub
- canonical benchmark
- governance layer
- variable definition system

Qlib answers exactly one question: **do structural variables, injected as external inputs, produce incremental feedback in a real-market benchmark?**

## Boundary Contract

Qlib is **not allowed** to:
- import main system code
- read canonical `Data/releases/` directly
- write to Deformation outputs
- write to Learning Hub
- update latest pointers
- define structural variables
- mutate benchmark manifests
- write to `Output/deformation_runs/`
- write to `Output/system_learning/`

Qlib is **allowed** to:
- read copied sandbox input (`sandbox_input/`)
- write isolated Qlib workspace files (`qlib_workspace/`)
- write raw benchmark metrics (`qlib_output/`)
- fail without affecting the main system

## Key Principles

- **candidate != canonical**
- **sandbox != system**
- **executor != authority**
- **feedback != truth**

## Data Flow (unidirectional)

```
OpenBB / Harvester
    -> Immutable Market Data Release
    -> Deformation Feature Release
    -> Sandbox Exporter
    -> sandbox_input/ (read-only copy)
    -> Qlib Runner (subprocess, isolated env)
    -> qlib_output/ (raw metrics)
    -> Metrics Collector
    -> feedback_decision.json
    -> Learning Hub Event
```

Qlib cannot:
- modify `Data/releases/`
- write deformation features
- write canonical ledger
- directly trigger Learning Hub
- import main system `src/`

## Directory Structure

```
ExternalTools/qlib_benchmark_runner/   # Qlib executor (external)
Workbench/src/benchmarks/market_feedback/  # Orchestration layer
Output/benchmarks/market_feedback/<benchmark_id>/  # Per-run isolation
tests/benchmarks/market_feedback/      # Isolation tests
```

## Execution

```bash
# Step 1: Create benchmark and export sandbox input
python -m benchmarks.market_feedback.create_benchmark \
  --benchmark-id 2026-05-05_OPENBB_QLIB_MFB_001 \
  --market-release 2026-05-05_OPENBB \
  --deformation-release 2026-05-05_WEEKLY

# Step 2: Run external executor (subprocess)
python -m benchmarks.market_feedback.run_external_executor \
  --benchmark-id 2026-05-05_OPENBB_QLIB_MFB_001

# Step 3: Collect and classify feedback
python -m benchmarks.market_feedback.collect_feedback \
  --benchmark-id 2026-05-05_OPENBB_QLIB_MFB_001
```

## Isolation Tests

```bash
pytest tests/benchmarks/market_feedback/ -v
```
