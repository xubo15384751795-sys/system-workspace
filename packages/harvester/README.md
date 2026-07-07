# Structural Risk Harvester

Structural Risk Harvester acquires public financial and macro-risk data, records
provenance, and publishes immutable release bundles for downstream structural
risk research systems.

Harvester is deliberately not a modeling layer. It does not decide how a signal
enters Deformation equations. Its job is to make datasets discoverable,
verifiable, and reproducible through manifest-backed files.

## What It Produces

Finalized releases live under `data/exports/<release_id>/` and expose only the
contract-governed surface:

- `catalog.json`
- `release_digest.txt`
- `.finalized`
- `manifests/<dataset_id>.manifest.json`
- `provenance/<dataset_id>.provenance.json`
- `data/<dataset_id>.<ext>`

Consumers should start with `catalog.json`, read dataset manifests, verify data
file sha256 checksums, and then load the declared data files. Raw, processed,
and corpus staging directories are provider-internal.

## Current Providers

Implemented acquisition backends include:

- FRED macro, rates, and credit series
- Federal Reserve H.4.1 fields through direct Data Download Program CSV, with
  FRED bridge fallback when configured
- U.S. Treasury FiscalData
- SEC EDGAR filing pulse
- CBOE direct CSV and delayed JSON endpoints
- OpenBB-backed FRED, Tiingo, and selected market-data routes
- External indicators such as OFR FSI where public files are available

OpenBB is used only as an acquisition engine inside Harvester providers. The
published identity remains provider-native, such as `fred`, `tiingo`, or `cboe`.

## Common Commands

Run tests:

```bash
python3 -m pytest -q
```

List known releases:

```bash
python3 -m harvester.cli list-releases
```

Stage a complete release:

```bash
python3 -m harvester.cli stage-complete-release 2026-05-10-r1 --as-of-date 2026-05-10
```

Validate a staged release without sealing it:

```bash
python3 -m harvester.cli finalize-release 2026-05-10-r1 --dry-run
```

Finalize and update `latest`:

```bash
python3 -m harvester.cli finalize-release 2026-05-10-r1 --no-dry-run
```

Run a production preflight:

```bash
python3 -m harvester.cli preflight
```

Generate the next UTC release id:

```bash
python3 -m harvester.cli next-release-id
```

Run the daily release path:

```bash
python3 -m harvester.cli daily-release --as-of-date 2026-05-10
```

## Contract Discipline

The release contract is frozen at schema family version `1.0` in `contracts/`.
A release is valid only when every manifest validates, every declared data file
exists and matches its recorded size and sha256, every provenance file agrees
with its manifest, and every file under the release `data/` directory is
declared by a manifest.

Finalized releases are immutable. Corrections are published as new releases.
