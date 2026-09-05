# Data Boundary

## Principle

Structural Deformation is a framework analysis engine.
It consumes admitted evidence.
It does not acquire external provider data.

Structural Risk Harvester is the acquisition and release layer.
It fetches public/provider data, validates it, and publishes releases with catalog, manifest, provenance, hashes, and schemas.

The Workbench is the product layer.
It exposes current status, evidence views, reports, next actions, and user-facing commands.

## Allowed in Deformation

Deformation MAY:

- read Harvester releases
- validate catalog, manifest, provenance, hashes, and schemas
- consume admitted evidence panels
- transform admitted evidence into structural inputs
- compute M/D/K/X, Sigma, morphology, residuals, and diagnostics
- produce framework-specific reports and run packages
- publish framework outputs to the Workbench contract

## Forbidden in Deformation

Deformation MUST NOT:

- call FRED, SEC, Treasury, CFTC, AlphaVantage, Polygon, Tiingo, CBOE, IMF, or other external providers directly
- construct external provider clients
- read provider API keys
- perform external HTTP acquisition
- manage raw provider caches
- implement provider retry/rate-limit behavior
- publish Harvester-style releases
- decide provider admission policy

## Official Data Boundary

The official Deformation data boundary is:

```text
src/data_access/
```

The preferred path is:

```text
Harvester release
-> catalog / manifest / provenance validation
-> admitted evidence bundle
-> structural input snapshot
-> Deformation diagnosis
```

## Legacy Acquisition Shims

The following modules are retained temporarily for backward compatibility and migration only:

- `src/data/data_sources.py`
- `src/data/adapters/public_adapters.py`
- `src/data/gateway/data_hub.py`
- `src/data/external_downloads.py` (Phase A deprecated fail wrapper; no active acquisition)

New code must not depend on these modules.

`src/data/external_downloads.py` is no longer an active acquisition shim.
It is retained only as a temporary fail wrapper for old imports. External
indicator acquisition now belongs in Structural Risk Harvester, and
Deformation must consume the resulting admitted evidence through `src/data_access/`.

## Migration Direction

- Move provider acquisition to Structural Risk Harvester.
- Keep Deformation as an admitted-evidence consumer.
- Expose Framework outputs through Workbench protocols.
