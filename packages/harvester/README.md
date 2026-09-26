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
- Cross-asset ETF EOD chain: Tiingo, Massive, then
  bounded yfinance fallback
- OpenBB-backed FRED, Tiingo, and selected market-data routes
- External indicators such as OFR FSI where public files are available

OpenBB is used only as an acquisition engine inside Harvester providers. The
published identity remains provider-native, such as `fred`, `tiingo`, or `cboe`.

The ETF chain reads `TIINGO_API_KEY` and `MASSIVE_API_KEY` from the scheduler
environment. Missing keys are recorded as provider-unavailable and do not
trigger a network request. The selected source for each ticker is recorded in
the `cross_asset_daily_panel` release manifest.
The default full provider route consumes the canonical logical secret
`FRED_API_KEY` from the same secure file; the scheduler SecretProvider accepts
`OPENBB_FRED_API_KEY` only as a compatibility input and normalizes it before
Harvester/provider code runs. Without the canonical secret, Harvester preflight
fails closed before any FRED-backed acquisition.
The workspace-level `configs/source_registry.yaml` is the semantic route
contract. It keeps Tiingo/Massive as the only authoritative ETF routes,
requires a reviewed Tiingo/Massive parity report before the Massive fallback
can be decision-usable, marks yfinance as diagnostic-only, and preserves publisher identity for ECB,
OFR, NY Fed, CFTC, FINRA, and NYU V-Lab indicators. The parity lane in
`harvester.core.etf_parity` is shadow-only until its observed window is
explicitly reviewed.

### Configure the Tiingo key for the scheduled run

The default `com.system.daily-run` path reads provider keys from the local file
`~/.config/system/provider.env`. The file is parsed as plain `KEY=VALUE` data
(never executed as shell code), must be owned by the current user, and must be
mode `600` or stricter. Create it locally without committing it:

```bash
mkdir -p ~/.config/system
chmod 700 ~/.config/system
read -r -s "TIINGO_API_KEY?Tiingo API key: "; echo
umask 077
printf 'TIINGO_API_KEY=%s\n' "$TIINGO_API_KEY" > ~/.config/system/provider.env
unset TIINGO_API_KEY
chmod 600 ~/.config/system/provider.env
```

Create the token in your Tiingo account, then use the same file for `MASSIVE_API_KEY`
later if that provider is enabled. An already-exported, non-empty environment
variable takes precedence over the file. `SYSTEM_PROVIDER_SECRETS_FILE` can be
set to use another mode-600 path. Never paste the token into source control or
chat. Verify only the presence of the key (not its value) before the next
scheduled run.

On Linux/systemd, the host may instead inject `FRED_API_KEY` through the unit's
credential/environment mechanism or set `SYSTEM_PROVIDER_SECRETS_FILE` to a
mode-600 file. Harvester/domain providers consume only the canonical
`FRED_API_KEY`, so changing the host secret source does not require a domain or
registry change.

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

Run the explicit Tiingo/Massive parity shadow lane (it never changes the
scheduled release by itself):

```bash
python3 scripts/run_etf_provider_parity.py --period 60d
```

Check the real 14-day scheduled evidence window. Manual runs and tests are
excluded because only bundles marked `run_origin=launchd` count:

```bash
python3 scripts/verify_data_reliability_window.py
```

## Contract Discipline

The release contract is frozen at schema family version `1.0` in `contracts/`.
A release is valid only when every manifest validates, every declared data file
exists and matches its recorded size and sha256, every provenance file agrees
with its manifest, and every file under the release `data/` directory is
declared by a manifest.

Finalized releases are immutable. Corrections are published as new releases.
