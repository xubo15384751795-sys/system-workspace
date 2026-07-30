# P0-4 Compute Device Handoff

This is the execution contract for completing **P0-4 Freshness and Monitoring
Closure** on the compute/test device. The Mac remains the authoring, review,
merge, and progress-ledger device. Long refreshes, full verification, and
multi-day evidence collection belong on the compute device.

The source controls for P0-4 entered `main` through PR #17. The shared progress
state machine entered `main` through PR #18. The minimum source baseline is
`dddab69afa802a2ad818da546ebc50d412ddb507`; always use the latest clean
`origin/main` containing this file and record the actual tested SHA.

## Authority and success boundary

The authoritative definitions are:

- `SYSTEM_LARGE_SCALE_VALIDATION_ROADMAP.md`, section 7 and section 16;
- `governance/progress/validation_roadmap.yaml`, task `P0-4`;
- `governance/daily_pipeline_registry.yaml`;
- `governance/system_constitution.yaml`;
- the append-only `governance/progress/validation_progress_events.jsonl`.

P0-4 may move from `CI_GREEN` to `OPERATIONAL_VALIDATION` only when all of the
following are supported by evidence from one pinned source SHA:

1. the Harvester release is finalized and OFR FSI/CISS are fresh or within
   their governed publication lag;
2. the pre-consumption admission gate passes without a bypass;
3. all 19 refresh steps complete in order;
4. required Current artifacts come from the same run/release lineage;
5. full freshness verdict is `PASS`;
6. ordering issues and closure-chain issues are both zero;
7. authoritative and decision-adjacent monitoring coverage is 100%;
8. operator current-chain tests pass;
9. the SHA-bound merge verification verdict is `PASS`.

This first successful run does **not** complete P0-4. It starts the later
14-consecutive-day window with no partial refresh.

## Prohibited shortcuts

Do not:

- extend TTLs merely to turn a failure green;
- touch file mtimes or copy an old release into `latest`;
- use `--no-external` or `--no-preflight`;
- use partial averages or silent renormalization when required data are stale;
- manually write authoritative files under `Output/current/`;
- classify a required asset as research/manual/archived without a specific,
  reviewed routing decision and an accountable owner;
- commit `Data/`, `Output/`, credentials, provider responses, or proprietary
  market/house data;
- edit `PROJECT_PROGRESS.md` percentages by hand.

Any command failure is a stop condition. Preserve its output and diagnose the
cause before continuing.

## 1. Prepare a clean, pinned workspace

Use a fresh clone or a clean worktree. Do not run this protocol on a directory
with unrelated changes.

```bash
git fetch origin --prune
git switch main
git pull --ff-only origin main
git status --short
git rev-parse HEAD
```

`git status --short` must be empty. Record the full SHA printed by the last
command in the run evidence.

Use Python 3.12 or 3.13 and install the same dependency surfaces as the
authoritative GitHub merge gate:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip install -e "packages/framework[dev]"
.venv/bin/python -m pip install -e "packages/harvester[dev]"
.venv/bin/python -m pip install -e "packages/workbench[dev]"
.venv/bin/python -m pip install -e "packages/learning_hub[dev]"
```

Confirm the shared roadmap and the 19-step plan before any write:

```bash
./sys roadmap
./sys refresh --dry-run
```

The dry run must list pre-consumption admission plus steps 2 through 19.

## 2. Capture the failing baseline

Run the three audits before refreshing. Failure is expected at the starting
baseline, but the exact blockers must be retained:

```bash
.venv/bin/python scripts/freshness_validator.py --mode full --json
.venv/bin/python scripts/check_output_freshness.py --require-artifacts --json
.venv/bin/python scripts/artifact_monitoring_audit.py --strict --json
```

The known starting blockers were:

- stale OFR FSI and CISS release/cache content;
- 12 stale Current artifacts;
- 55 required authoritative or decision-adjacent monitoring coverage gaps.

Treat these numbers as a historical baseline, not a forced expectation. Record
the actual counts from the compute device.

Also record:

```bash
git status --short
git rev-parse HEAD
readlink Data/harvester/exports/latest
```

If `latest` is missing or not a release link, stop and repair the Harvester
workspace through its official exporter; do not create a manual link.

## 3. Build a real Harvester daily release

Run preflight explicitly:

```bash
.venv/bin/python -m harvester \
  --exports-root "$PWD/Data/harvester/exports" \
  preflight
```

Preflight must pass. Then build a fresh release without reusing provider cache
content:

```bash
.venv/bin/python -m harvester \
  --exports-root "$PWD/Data/harvester/exports" \
  daily-release \
  --no-cache \
  --notes "P0-4 operational validation"
```

Do not add `--no-external` or `--no-preflight`. The command must finish with
status `finalized`. Record the release ID, as-of date, vintage date, provider
statuses, and the path selected by `latest`.

Validate and monitor the finalized release:

```bash
.venv/bin/python -m harvester \
  --exports-root "$PWD/Data/harvester/exports" \
  validate-catalog Data/harvester/exports/latest
.venv/bin/python -m harvester \
  --exports-root "$PWD/Data/harvester/exports" \
  monitor --max-age-days 3
```

If OFR FSI or CISS is unavailable, failed, empty, or older than its governed
content clock, stop. A finalized release alone is not freshness evidence.

## 4. Run the authoritative 19-step refresh

Run the default path without skip flags:

```bash
./sys refresh
```

Required behavior:

- admission passes before any producer executes;
- steps run from `1/19` through `19/19`;
- the first failed step stops all descendants;
- the command exits zero;
- all required outputs are verified.

If admission still blocks, preserve the blockers and return to the Harvester
release. Do not bypass admission.

The two weekly products are intentionally outside the daily 19-step chain.
Build them separately:

```bash
.venv/bin/python scripts/commands/weekly/build_data_gaps.py
.venv/bin/python scripts/commands/weekly/build_change_analysis.py
```

Do not change their schedule classification to daily merely to clear age.

## 5. Prove freshness, lineage, and monitoring closure

Run:

```bash
.venv/bin/python scripts/freshness_validator.py --mode full --json
.venv/bin/python scripts/check_output_freshness.py --require-artifacts --json
.venv/bin/python scripts/artifact_monitoring_audit.py --strict --json
.venv/bin/python -m pytest -q \
  tests/test_current_artifact_chain_operator.py \
  tests/test_freshness_governance_operator.py \
  tests/test_harvester_bundle_operator.py
```

Acceptance requires:

- full freshness verdict `PASS`;
- zero stale required Current artifacts;
- zero ordering issues;
- zero closure-chain issues;
- one consistent Current `run_id` and Harvester release lineage;
- zero unclassified assets;
- zero required monitoring coverage gaps;
- all operator tests pass.

The initial strict monitoring audit may still report required gaps after a
successful refresh. Close them in evidence-sized batches by adding a real
producer/content clock contract or a specific routing decision with owner and
rationale. Re-run the strict audit after every batch. Never use a catch-all
classification.

## 6. Run the full SHA-bound verification

After the runtime checks pass, run the repository's authoritative merge gate:

```bash
./sys verify --merge
./sys verify --check
```

The generated manifest is
`Output/verification/merge_gate_manifest.json`. It must:

- name the exact `git rev-parse HEAD` SHA;
- report verdict `PASS`;
- report zero bypasses;
- contain all ten successful verification steps.

The merge gate intentionally excludes operator-state tests; the operator tests
in section 5 are therefore separate mandatory evidence.

## 7. Evidence record

Retain a concise, non-sensitive run record containing:

| Field | Required value |
|---|---|
| source SHA | full tested commit SHA |
| branch | isolated `codex/p0-4-...` branch |
| run start/end | UTC timestamps |
| Harvester release | release ID, as-of and vintage dates |
| provider result | OFR FSI and CISS status/content dates |
| admission | PASS, zero bypasses |
| refresh | 19/19 successful steps |
| Current lineage | one run ID and one source release |
| full freshness | PASS; stale count 0 |
| ordering/closure | 0 / 0 |
| monitoring | required gaps 0; unclassified 0 |
| operator tests | all pass |
| merge verification | PASS and SHA match |
| exceptions | none, or explicit blocker with owner |

Raw `Data/` and `Output/` remain local and ignored. Commit only source,
governance contracts, non-sensitive summaries, and routing decisions needed to
close validated gaps.

## 8. Publish and update shared progress

Push the compute-device changes on an isolated branch and open a draft PR.
The PR must identify the tested SHA, Harvester release, run ID, audit counts,
operator results, merge-manifest verdict, and any remaining blockers. Wait for
push/PR checks to be fully green.

After human review accepts the evidence, append the P0-4 transition through the
state-machine command. Do not edit the JSONL event or generated percentage
manually. The accepted command should have this shape, with real evidence URLs
and the accepted commit SHA substituted:

```bash
./sys roadmap transition P0-4 OPERATIONAL_VALIDATION \
  --actor "<reviewer>" \
  --reason "Compute-device P0-4 operational validation accepted" \
  --evidence "<pull-request-or-run-url>" \
  --commit-sha "<accepted-sha>" \
  --criterion same_run_closure=satisfied \
  --criterion full_freshness_pass=satisfied \
  --criterion required_coverage=satisfied \
  --criterion fourteen_day_no_partial=in_progress \
  --next-gate "Accumulate 14 consecutive days with no partial refresh"
python3 scripts/roadmap_progress.py render --output PROJECT_PROGRESS.md
python3 scripts/roadmap_progress.py validate
```

Only after that event is reviewed and merged does the shared percentage move.
After the first accepted run, continue the same protocol daily for 14
consecutive days. Any partial refresh, bypass, lineage break, stale required
input, or monitoring regression resets the uninterrupted P0-4 evidence window.
