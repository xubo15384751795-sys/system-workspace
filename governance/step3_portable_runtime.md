# Step 3 — Portable Runtime Gate

Date: 2026-09-12

Status: `PASS_DEFAULT_RUNTIME_WITH_EXPLICIT_NON_DEFAULT_DEBT`

This gate covers the installed default runtime surface. It does not claim a
successful provider run, provider admission, or a reliability window.

## Runtime boundary

`RuntimeContext` is resolved and activated by `system_cli.app.main()` before
the application command is dispatched. It owns:

- workspace, data root, and output root;
- external roots, `SecretProvider`, scheduler metadata, host, and clock;
- provider configuration and execution identity.

The default execution spine receives that context through the daily payload
and sequence context. The sequence executor derives step paths and input
artifacts from it. Default subprocess steps receive the installed workspace
packages and do not construct or forward `PYTHONPATH`.

The canonical secret is `FRED_API_KEY`. The compatibility alias
`OPENBB_FRED_API_KEY` is normalized only by the `SecretProvider` boundary.
Mode-600 files are host implementations of that provider; domain code does
not depend on a user-specific secret path.

## Gate evidence

| Gate | Result | Evidence |
|---|---|---|
| Locked workspace install | PASS | `uv sync --locked --all-packages` completed successfully; 341 packages resolved, 113 checked |
| Clean-shell import | PASS | `env -u PYTHONPATH .venv/bin/python -c 'import system_cli, system_runtime, verity, orchestration, harvester'` |
| Clean-shell CLI | PASS | `env -u PYTHONPATH .venv/bin/verity --workspace ... pipeline validate`; 83 steps, 40 edges |
| Temporary data/output roots | PASS | clean-shell `pipeline validate` and `daily --dry-run` with `SYSTEM_DATA_ROOT` and `SYSTEM_OUTPUT_ROOT` in a temporary directory |
| Alternate workspace root | PASS (bounded) | temporary workspace fixture containing only the registry and pipeline schema passed `pipeline validate` and `daily --dry-run` |
| Synthetic scheduler | PASS | `RunOutcome` business status and exit code are unchanged between launchd and synthetic systemd; only scheduler identity changes |
| Absolute Mac path scan | PASS | zero `/Users/<user>/...` matches in active production Python roots |
| Default PYTHONPATH dependency | PASS | application strips ambient `PYTHONPATH`; default sequence executor contains no `PYTHONPATH` construction |

The alternate-workspace and temporary-root checks are bounded runtime checks,
not a full provider acquisition or publication rehearsal.

## Scheduler-neutral identity

Run evidence now carries `trigger_kind`, `scheduler_kind`, `scheduler_id`,
`schedule_id`, `trigger_id`, `host_id`, `run_id`, and `release_id`. Reliability
qualification uses the explicit scheduled identity contract and accepted
release/scheduler values; it no longer uses `run_origin == launchd` as the
meaning of formal execution.

The current verifier state remains `PENDING` with `observed_runs: 0`. This is
expected because the new identity contract intentionally does not reinterpret
older bundles as qualified evidence.

## Explicit remaining debt

- The tracked/installed LaunchAgent plist still contains historical
  control-plane `PYTHONPATH` and host-specific observability-file entries. The
  scheduled shell adapter clears `PYTHONPATH` before `verity` starts. Plist
  reconciliation remains an independent control-plane slice and was not
  changed for this gate.
- Non-default shadow, parity, DVC, archive, and legacy compatibility tools
  still contain explicit process-boundary or package-resource path assumptions.
  They are inventory debt, not default scheduled-path dependencies.
- Some package-resource/configuration helpers still accept explicit
  user-supplied paths via `expanduser()`; these are input normalization, not
  workspace discovery. The remaining source-parent fallbacks are limited to
  non-default/archive/operator surfaces and remain migration candidates.

## Outside this gate

- FRED credential acquisition and the second full scheduled-path rehearsal;
- provider admission and provider fallback semantics;
- the 14-day reliability qualification window;
- installed LaunchAgent reconciliation;
- Step 0 release-boundary changes or automatic cleanup of the dirty worktree.

The Step 3 implementation preserves the existing dirty worktree and does not
reset, clean, stash, or commit it.
