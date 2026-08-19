# Structural Deformation Research System

Framework does not fetch the world.
Framework consumes admitted evidence.

For the data boundary, see `DATA_BOUNDARY.md`.

Data layer has been extracted to peer system: `../Structural Risk Harvester/`.

Research system for studying financial-market structural deformation, compression failure, and crisis-regime entry.

The project operationalizes an Anchor-Mismatch framework: market stress is not treated as a single volatility score or a one-factor pricing error. Instead, the system tracks how mismatch, feasible degrees of freedom, transition curvature, and hidden shadow pressure co-evolve under data evidence, event order, reflexive feedback, and dynamic state evolution.

At runtime the system turns public data and event logs into structural snapshots. Each snapshot records proxy evidence, primitive-state estimates, operator-path diagnostics, ODE solver diagnostics, shadow-maturity pressure, mean-field gap, belief-state uncertainty, singular-regime checks, and interpretation artifacts.

## Structural Risk Lab

This repository is a code-managed research operating system, not a generic wiki
and not "Obsidian plus RAG". Its governing flow is:

```text
raw evidence -> cleaned data -> proxy/diagnostic code -> wiki interpretation -> paper output
```

The project combines two kinds of discipline:

- knowledge compilation: raw material is compiled into structured evidence,
  diagnostics, wiki pages, reports, and paper outputs over time
- boundary discipline: evidence, code, knowledge, papers, prompts, reports, and
  tests have separate authority and may not silently replace each other

Layer ownership:

- `data/`: evidence layer for raw, processed, external, manifest, and snapshot material
- `src/`: capability layer for ingestion, preprocessing, proxies, benchmarks, diagnostics, replay, visualization, and reports
- `wiki/`: policy/knowledge layer for variables, mechanisms, cases, institutions, literature, datasets, methods, and claims
- `papers/`: expression layer for paper-specific drafts and LaTeX workspaces
- `prompts/`: protocol layer for human-guided Codex/LLM operating rules; this does not assume an autonomous multi-agent runtime
- `Output/deformation_runs/`: generated case memos, benchmark reports, figures, and run packages
- `tests/`: verification layer for architecture boundaries, data quality, benchmark separation, proxy integrity, and no-lookahead behavior

Hard pollution rules:

1. Research corpus documents are not formal data unless registered as structured datasets.
2. Benchmarks such as NFCI, VIX, MOVE, STLFSI, and OFR FSI cannot enter `Sigma_t`
   proxy construction unless explicitly marked as benchmark/control, not proxy core.
3. Wiki interpretation cannot create new empirical claims without adding them to
   `wiki/claims/claim_registry.md`.
4. Paper text cannot cite code outputs unless the output has a data manifest,
   frequency policy, and no-lookahead check.

Run the research OS audit:

```bash
python3 scripts/audit_research_os.py
```

## What This System Is For

This project is meant for research workflows such as:

- testing whether stress episodes are better described as structural deformation rather than scalar risk elevation
- mapping observable public indicators into latent channels `M / D / K / X`
- examining whether event order matters through non-commutative operator diagnostics
- detecting singular-regime candidates through joint DoF collapse, curvature spike, and forced shadow realization
- comparing coupled shadow pressure against a decoupled representative benchmark through the mean-field gap
- replaying historical windows and scenario labs with reproducible evidence and provenance
- exporting machine-readable JSON, readable HTML, and UI/API views for inspection

The system is intentionally not a trading model, not a CAPM replacement estimator, and not a forecasting-dominance claim. It is a research instrument for representing, measuring, and inspecting structural deformation.

## Core Idea

The framework starts from the claim that global scalar compression loses critical structural information when markets are state-dependent, non-commutative, reflexive, and dimensionally time-varying.

The operational channels are:

- `M`: anchor mismatch, such as price-funding, verifiability, or liquidation-anchor gaps
- `D`: effective degrees of freedom, meaning feasible pricing, hedging, funding, liquidation, and intervention capacity
- `K`: transition-geometry curvature, meaning instability in the local shock-to-next-state map
- `X`: aggregate shadow pressure, meaning hidden or delayed risk mass not fully visible in the current observability layer

The newer primitive layer sits underneath those channels:

```text
S, A, L, V, P, tau
  -> subject configuration
  -> anchor configuration
  -> liquidation-path feasibility
  -> verifiability density
  -> positional power
  -> latency

  -> derived M, D, K, Xagg
```

This means `M/D/K/X` remain the stable public interface, while the system can now carry a more explicit six-variable structural interpretation.

## Runtime Pipeline

The normal snapshot path is:

```text
DataHubBridge structural presets
  -> DataEvidenceManifest / data-quality admission
  -> proxy baskets for M/D/K/X
  -> structural operator sequence from event logs
  -> primitive state layer: S/A/L/V/P/tau
  -> shadow maturity profile and mean-field gap
  -> Diffrax/JAX or SciPy ODE evolution
  -> distributional belief state
  -> singular-regime detector
  -> anomaly/reflexivity/narrative checks
  -> snapshot store + JSON/HTML/UI/API output
```

The snapshot is the central artifact. It contains both the current reading and the evidence trail needed to inspect how the reading was produced.

## Mathematical Tool Layer

`src/dynamics/` provides the state-evolution layer.

The preferred engine is `DiffraxODEEngine` in `src/dynamics/state_evolution.py`:

- uses `Diffrax + JAX` when installed
- supports adaptive solvers such as `Tsit5`, `Dopri5`, `Dopri8`, and `Kvaerno5`
- falls back to SciPy and then a small RK4 path if optional dependencies are unavailable
- exposes ODE diagnostics including backend, solver, step count, threshold hit time, spectral abscissa, Jacobian Frobenius norm, and spectral-abscissa drift
- passes threshold hit time through snapshot provenance as `structural_singular_time` when available
- enables JAX-based Jacobian calculations for curvature and future sensitivity work

The old `ScipyODEEngine` import remains as a compatibility alias, so older scripts continue to run.

Configured in `config.yaml`:

```yaml
ode_params:
  backend: auto
  solver: tsit5
  dt: 1.0
  horizon: 4
  rtol: 0.00001
  atol: 0.0000001
  max_steps: 4096
```

## Shadow Maturity And Mean-Field Gap

`src/derivation/structural_layers.py` builds the new derived structural layer:

- `StructuralPrimitiveState`: reduced six-variable primitive state
- `ShadowMassState`: multi-bucket hidden pressure profile
- `MeanFieldGapState`: gap between coupled shadow load and a decoupled representative benchmark

The shadow layer currently uses an interpretable multi-compartment reduced form:

```text
immediate   0-30d
short       1-3m
medium      3-12m
long        12m+
```

Each bucket carries mass and realization intensity. The aggregate forced-realization pressure is used by the singular detector as `Pi_t`.

This is the engineering bridge toward the paper's measure-valued shadow equation. The current implementation is deliberately reviewable and stable; it can later be replaced or extended with a fuller spectral/Fokker-Planck solver without changing the snapshot interface.

## Singular-Regime Logic

`src/derivation/singular_detector.py` now supports two compatible checks:

- legacy scalar stress score for continuity with earlier snapshots
- joint hitting condition:

```text
D_t <= epsilon_D
K_t >= K_star
Pi_t >= Pi_star
```

Here `Pi_t` is the forced realization pressure from `ShadowMassState` when available. This moves crisis detection closer to the paper's definition: crisis is a structural singular regime candidate, not merely a high stress sum.

Configured in `config.yaml`:

```yaml
thresholds:
  sigma: 2.0
  protocol:
    calibration_mode: fixed_config
    frozen: true
    training_window: null
    evaluation_window: null
  joint_hitting:
    enabled: true
    dof_collapse: -0.65
    curvature_spike: 0.65
    forced_realization: 0.65
```

The `protocol` block records whether thresholds are fixed configuration values or tied to an explicit training/evaluation split. It is metadata today, not a full calibration engine: forward-window threshold calibration still has to be implemented before the system can claim a complete pre-registered evaluation workflow.

Each singular check also leaves detector diagnostics in provenance, including scalar-threshold hits, joint-hitting status, distributional triggers, forced-realization pressure, and `structural_singular_time` when a current-state joint hit or ODE horizon hit is observed.

## Structural Operator Layer

Events are modeled as state-dependent operators over `M/D/K/X`, not just labels in an event table.

Important files:

- `src/operators/operator_schema.py`: operator metadata and typed sequence objects
- `src/operators/operator_registry.py`: default taxonomy for compression, curvature, shadow transfer, realization, and intervention
- `src/operators/event_to_operator.py`: maps event-log rows into ordered operators
- `src/operators/operator_algebra.py`: apply/compose logic, commutator vectors, Lie-bracket approximations, and non-commutativity scores
- `src/operators/operator_diagnostics.py`: sequence diagnostics such as compression ratio, shadow transfer, curvature amplification, mismatch amplification, singular pressure, non-commutativity, and reduced path-rank witnesses

The system records both finite flow-order effects:

```text
O_b(O_a(z)) - O_a(O_b(z))
```

and a near-identity Lie-bracket approximation:

```text
[X, Y](z) = DY(z)X(z) - DX(z)Y(z)
```

This makes path order a measurable structural object.

For paper-alignment audits, operator diagnostics also report a reduced finite-sequence path-rank witness:

```text
path_rank_witness_count
path_rank_max_output_separation
path_rank_mean_output_separation
```

These fields test whether adjacent operator-order swaps produce separated `M/D/K/X` outputs for the realized event sequence. They are not the full positive-measure path-rank condition from the paper, but they make the path-rank idea inspectable in code.

## Data And Evidence Layer

`src/data/gateway` exposes a unified `DataHub` and `DataHubBridge` for public research data.

Supported provider families include:

- `fred`
- `fed_h41`
- `treasury`
- `sec`
- `ecb`
- `cftc`
- `alpha_vantage`
- `stooq`
- `tiingo`
- `massive`
- `nasdaq_data_link` / `ndl` / `quandl`
- `cboe`
- `oecd`
- `bis`
- `imf`
- `ffiec`

Stable official-source defaults are FRED, Federal Reserve releases, Treasury
FiscalData, SEC EDGAR, ECB SDW, and CFTC public reporting. Rate-limited market
data providers are registered behind the same DataHub contract but should be
used for selected instruments/windows rather than broad historical sweeps on
free tiers. OECD/BIS/FFIEC generic adapters accept a direct official CSV URL via
`resource` or `metadata.url` when an endpoint needs a specialized query shape.

The preferred entrypoint is structural presets rather than raw endpoint calls. Presets are named by structural role first, for example:

- `mismatch_policy_funding_gap_us`
- `dof_funding_access_us`
- `curvature_jump_instability_us`
- `shadow_verifiability_issuer_core`

Data-quality behavior:

- `DataEvidenceManifest` records per-series and per-channel evidence quality
- snapshot provenance includes `data_quality`, fallback status, and real-series counts
- all-mock or all-fallback research runs are escalated so demo data cannot silently pass as research evidence
- provider adapters expose retries, cache paths, and fallback metadata

Direct provider calls still exist, but the system tries to preserve structural semantics: `preset_name`, `channel`, `measurement_block`, and `evidence_role`.

## Research Claim Boundaries

Every major metric, indicator, and output should be read through one of three
feature layers:

- `paper_aligned`: main-flow research claims corresponding to the paper, such
  as M/D/K/X aggregation, `sigma_t`, singular detection, primitive-to-channel
  mapping, ODE evolution, shadow mass, commutator/Lie-bracket operator views,
  and mean-field gap against the configured benchmark.
- `engineering_required`: implementation controls that make the system
  auditable but are not paper claims, such as provenance, data-quality
  manifests, cache behavior, threshold protocol metadata, and evidence
  escalation.
- `exploratory`: research-lab extensions beyond the current paper scope, such
  as ML anomaly/narrative/reflexivity signals, graph coupling bands,
  distributional belief breach probabilities, and finite path-rank witnesses.

The compatibility `Snapshot` object still contains all fields used by older
tests, storage, and exports. For research-facing interpretation, use the
explicit projections:

- `snapshot.core()` returns `SnapshotCore`, the paper-aligned main flow.
- `snapshot.extension()` returns `SnapshotExtension`, optional exploratory
  metadata that should not be cited as a main paper result.

The Streamlit UI follows the same split. `Paper Dashboard` is the default
SRC/UCL-facing view; `Engineering Dashboard` is for admin/debug evidence
inspection; `Exploratory Lab` is for research ideas outside the frozen paper
claim.

The main pipeline now also has an explicit run policy:

```yaml
pipeline:
  run_extensions: false
  run_belief_extension: false
  run_ml_extensions: false
  run_narrative_extension: false
  persist_extension_outputs: false
```

With extensions disabled, the pipeline still builds the paper-aligned core
state and engineering audit trail, but does not run or persist exploratory ML,
narrative, reflexivity, or belief outputs.

## Evidence-Aware Routing

`DataHub` remains the concrete provider gateway, but evidence selection is now
mediated by `EvidenceRouter`. Instead of choosing only by provider name, callers
can ask for structural evidence by role:

```python
hub.route_evidence({
    "channel": "D",
    "measurement_block": "funding_access",
    "evidence_role": "proxy",
})
```

The router returns candidate structural presets, provider ordering, and
capability scores. Provider capabilities are exposed through:

- Python: `hub.provider_capabilities()`
- Runtime API: `StructuralSystemAPI.provider_capabilities()`
- HTTP API: `GET /hub/capabilities`
- HTTP API: `POST /hub/route`

Pipeline provenance records `evidence_routes` and `pipeline_stages`, so a
snapshot can be audited from structural evidence intent through provider
selection, proxy construction, paper diagnostics, engineering audit, and
snapshot assembly.

## Distributional Belief Layer

The scalar `ProxyReading(M, D, K, X)` remains the compatibility interface, but snapshots can also carry uncertainty-aware belief state:

- `src/derivation/belief_builder.py` builds `StructuralBeliefState`
- `DistributionState` and `ChannelBeliefState` store transformed means, variances, quantiles, breach probabilities, and singular-mass estimates
- `ChannelDistributionState` summarizes rolling proxy-history distributions and is stored in provenance

This is intentionally incremental. The system starts with explainable distribution summaries, while the dependencies now include `NumPyro` and `BlackJAX` for future Bayesian upgrades.

## Simulation And Benchmarks

`src/simulation/` contains a Santa Fe-style scenario lab that simulates leverage, funding stress, collateral shocks, dealer capacity, network concentration, policy delay, hidden load, shadow realization pressure, and mean-field gap.

`src/benchmarks/` contains comparator stress measures and replay tools. These are useful for checking whether structural channels add information relative to simpler volatility-only, liquidity-only, or broad systemic-risk proxies.

The simulation output is coarse-grained back to:

```text
M, D, K, X, Sigma, singular_flag, mean_field_gap, forced_realization_pressure
```

## Runtime API

The project exposes a stable service boundary:

- `src/terminal/`: application service for health, runtime, data fetch, snapshot run, and snapshot reads
- `src/api/`: FastAPI adapter over that service
- `src/runtime/`: assembly, assets, evidence store, and system API

Run the API:

```bash
python3 scripts/run_api.py --host 127.0.0.1 --port 8787
```

Use configured real-data providers instead of mock mode:

```bash
python3 scripts/run_api.py --real-data
```

Core endpoints:

- `GET /health`
- `GET /runtime`
- `GET /series`
- `GET /data?series_ids=FRED:VIXCLS&start=2026-01-01&end=2026-04-20` (bounded query window)
- `GET /hub/providers`
- `POST /hub/series`
- `POST /hub/events`
- `POST /hub/filings`
- `POST /hub/positions`
- `POST /snapshots/run` with JSON body `{"run_date":"2026-04-20","run_type":"WEEKLY"}`
- `GET /snapshots`
- `GET /snapshots/{run_date}`

## UI

Run:

```bash
streamlit run app.py
```

The Streamlit UI includes:

- current-state proxy cards and regime badges
- structural history charts
- graph/state explorer
- scenario lab readouts
- research event logging
- snapshot archive
- reflexivity tracker

The next natural UI upgrade is a paper-diagnostic panel showing primitive hierarchy, shadow maturity profile, mean-field gap, singular surface, and CAPM-local boundary status.

## Output Artifacts

Run:

```bash
python3 assembly.py
```

Outputs are written to the configured `output.dir`, usually:

```text
/Users/a1/System/Output
```

Each exported run can write:

- `YYYY-MM-DD_RUN-TYPE.json`
- `YYYY-MM-DD_RUN-TYPE.html`
- `YYYY-MM-DD_RUN-TYPE.html.png` on macOS through `qlmanage`

Runtime DuckDB and Parquet mirrors are written under the configured `data.root` path.

## DataHub CLI Examples

Fetch a structural preset:

```bash
python3 scripts/run_datahub.py structural \
  --start 2026-01-01 \
  --end 2026-04-22 \
  --preset mismatch_policy_funding_gap_us
```

Fetch a direct provider series in mock mode:

```bash
python3 scripts/run_datahub.py series --mock \
  --start 2026-01-01 \
  --end 2026-01-10 \
  --request '{"provider":"fred","series_id":"DFF"}'
```

Benchmark the capture path:

```bash
python3 scripts/benchmark_data_capture.py --clear-cache --start 2007-01-01 --end 2009-06-30
python3 scripts/benchmark_data_capture.py --start 2007-01-01 --end 2009-06-30
```

## Configuration

Main controls live in `config.yaml`:

- `data.root`: runtime DuckDB/Parquet/data root
- `data_sources.enabled`: provider families
- `data_sources.api_keys`: optional API keys
- `data_sources.proxy_series_map`: proxy-basket mapping
- `operators`: event operator families, lookback, and max event count
- `mechanisms`: theory-plugin configuration
- `ode_params`: solver backend, horizon, tolerances, and threshold interpolation settings
- `thresholds`: scalar and joint-hitting singular thresholds plus protocol metadata for frozen train/evaluation boundaries
- `shadow_mass`: bucket weights and forced-realization parameters
- `output`: export directory and image controls
- `ui`: Streamlit host/port behavior
- `event_log`: event-log path

Useful environment variables:

- `FRED_API_KEY`
- `SEC_USER_AGENT`
- `ALPHA_VANTAGE_API_KEY`
- `TIINGO_API_KEY`
- `MASSIVE_API_KEY`
- `NASDAQ_DATA_LINK_API_KEY`

## Project Layout

```text
.
├── assembly.py           # compatibility entry -> src/runtime/assembly.py
├── app.py                # compatibility entry -> src/ui/app.py
├── config.yaml           # runtime parameters
├── data/                 # evidence layer; local symlink to configured data root
├── docs/                 # contracts, schemas, handoff, and project-facing docs
├── papers/               # paper-specific expression workspaces
├── prompts/              # human-guided LLM/Codex operating protocols
├── scripts/              # replay, benchmark, DataHub, API, and audit launchers
├── src/
│   ├── api/              # FastAPI adapter
│   ├── benchmarks/       # comparator stress measures and replay tools
│   ├── claims/           # executable claim guards and maturity tags
│   ├── core/             # contracts, models, pipeline, calibration, provenance
│   ├── data/             # DataHubBridge, adapters, quality, storage, distribution
│   ├── derivation/       # proxy, belief, structural layers, singular diagnostics
│   ├── diagnostics/      # morphology, residualization, and rejection gates
│   ├── dynamics/         # Diffrax/JAX/SciPy state evolution engines
│   ├── interpretation/   # market-state interpretation and action text
│   ├── mechanisms/       # theory plugins coarse-grained to M/D/K/X
│   ├── observability/    # public observability and evidence coverage
│   ├── operators/        # event-as-operator algebra and diagnostics
│   ├── proxies/          # structural proxy definitions and boundaries
│   ├── replay/           # replay capability contract placeholder
│   ├── reports/          # programmatic report builders
│   ├── research/         # exploratory research engine and hypothesis tools
│   ├── runtime/          # system API, assets, evidence store, assembly
│   ├── signals/          # signal decomposition utilities
│   ├── terminal/         # stable service boundary
│   ├── ui/               # Streamlit pages/components/helpers
│   ├── validation/       # walk-forward, ablation, target, and proxy checks
│   ├── simulation/       # scenario lab and phase diagram
│   ├── ml/               # optional anomaly/narrative/reflexivity detectors
│   └── output/           # JSON/HTML/image exports
├── wiki/                 # policy/knowledge layer and claim registry
└── tests/                # module-level and integration tests
```

## Tests

Run all tests:

```bash
python3 -m unittest discover -s tests
```

Current expected behavior: tests pass in mock/data-fallback mode, and some DataHubBridge warnings are normal when configured providers intentionally fall back to mock evidence.
