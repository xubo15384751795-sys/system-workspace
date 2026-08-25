# Operations

## Daily Release Path

Use `harvester daily-release` for unattended daily acquisition. It runs a
preflight, stages a release, finalizes it, and updates `latest` only if the
release passes validation.

```bash
python3 -m harvester.cli daily-release --as-of-date YYYY-MM-DD
```

The repository also includes a scheduler-friendly wrapper:

```bash
bash scripts/daily_release.sh 2026-05-10
```

Cron example:

```cron
30 22 * * 1-5 cd /Users/a1/Verity/packages/harvester && bash scripts/daily_release.sh >> /Users/a1/Verity/Data/harvester/ops.log 2>&1
```

Release ids follow UTC calendar dates and increment within the day:

```bash
python3 -m harvester.cli next-release-id
```

## Preflight

Preflight checks:

- Python version is at least 3.10.
- Required runtime packages import.
- `data/exports` exists and is writable.
- FRED credentials exist when FRED-backed providers are selected.
- OpenBB is importable when OpenBB-backed routes may be used.

OpenBB importability is currently a warning because OpenBB is an optional
backend, not the Harvester core.

```bash
python3 -m harvester.cli preflight
```

## Monitoring

Monitor the current `latest` release:

```bash
python3 -m harvester.cli monitor --max-age-days 3
```

`monitor` exits non-zero when `latest` is missing, its catalog is invalid, the
release integrity dry run fails, or another blocking check fails. Freshness
misses are warnings so an external monitor can decide whether to page or only
notify.

## Failure Reports

Failed unattended runs write JSON under:

```text
data/exports/.failures/<release_id>.<reason>.json
```

This is the alert handoff point for cron, launchd, or any external monitor.
The process exits non-zero on failed preflight or failed release creation.

## Legacy Releases

`20260426T074656Z` is a legacy pre-contract export. It is retained for audit
and comparison, but it does not satisfy the frozen catalog schema and is not
the `latest` pointer. Current consumers should enter through
`data/exports/latest`, which points at a schema-1.0 finalized release.
