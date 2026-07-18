# Git Workspace Policy

**Status:** precedent/reference as of 2026-07-18; not required reading
**Supersedes:** ad-hoc "nested clone vs submodule vs move under Workbench" options in older audit notes;
also updates the 2026-05-22 layout notes for day-to-day ops (active source now lives under
`packages/` in this monorepo).

Executable authority now lives in `.gitignore`, `.pre-commit-config.yaml`,
`scripts/_pre_push_hook.sh`, `scripts/bootstrap.sh`, and
`scripts/verify_merge.py`. This file preserves reasoning and recovery examples;
if it is never read, the enforced properties still hold.

This is the reference for how source code is versioned in `system-workspace`.
Path layout is in `governance/repo_layout_map.md`; directory ownership is in
`FOLDER_OWNERSHIP.md`.

---

## Production vs research workspaces (locked 2026-07-12)

| Branch | Purpose | Merge condition |
|---|---|---|
| `main` | Production truth. The launchd daily-run working copy **must stay on `main`**. | Full `pytest` green + `python3 scripts/daily_run.py --dry-run` pass |
| `research/<topic>` | One research line per branch, developed in an **independent git worktree** (never by switching the production checkout) | Infrastructure (additive, tested, ops defaults unchanged): green may merge. **Conclusion wiring into ops:** capability board pass + dated routing decision |
| `wip/<thread>` | Parallel threads (e.g. CaseLab) | Thread tests green + thread owner confirmation |

Rules:

1. **Production checkout never switches branches.** Research continues under
   `../System-research` (or another worktree path) via
   `git worktree add ../System-research research/<topic>`.
2. Research **code** that is additive and does not change production defaults may
   merge to `main` when green.
3. Research **conclusions** that change paper sizing / decision defaults require
   capability-board evidence plus a `governance/routing_decisions/` record — the
   same boundary frozen in nonlinear-framework prereg.
4. Do not leave multi-day WIP only in the production working tree; commit on the
   research branch or keep an explicit backup patch outside the repo.

---

## Decision (locked)

| Topic | Policy |
|---|---|
| Layout | **Sibling directories at workspace root** — no physical nest under `Workbench/data_providers/` or `Workbench/governance/` |
| Versioning | **Monorepo `packages/`** is the active source tree; historical git submodules for sister repos remain documented for migration compatibility |
| Fresh checkout | `git clone` + `./scripts/bootstrap.sh` |
| Generated data | **Never committed** in any repo — `Data/` and `Output/` stay gitignored at workspace root |
| Compatibility symlinks | Recreated by `scripts/bootstrap.sh`; not submodule paths |

Retired options (do not reopen without an explicit migration plan):

- **2a** — move harvester/hub under `Workbench/` (deferred indefinitely; high breakage cost)
- **Bootstrap-only clone** — sister repos gitignored with no `.gitmodules` (inconsistent; replaced by packages/ monorepo)

---

## Repository map

| Path | Role |
|---|---|
| `packages/workbench/` | Product, NLP, contracts, agent harness |
| `packages/framework/` | Deformation framework core |
| `packages/harvester/` | Data provider / harvester |
| `packages/learning_hub/` | Governance memory tool |

Parent repo owns:

- `governance/`, `protocols/`, `module_contexts/`, root `scripts/`, root `tests/`
- `configs/`, `docs/`, `semgrep_rules/`, `ExternalTools/qlib_benchmark_runner/`
- workspace-level docs (`README.md`, `FOLDER_OWNERSHIP.md`, `MODULES.md`, …)

---

## `.gitignore` contract

### Workspace root (`system-workspace/.gitignore`)

**Do list:**

- `Data/`, `Output/` — canonical artifact trees (regenerated locally)
- `OpenBB/` — external tooling install, not a submodule
- Virtualenvs, caches, secrets, logs, IDE noise (`.venv/`, `__pycache__/`, `.env`, `lightning_logs/`, `.DS_Store`, …)
- Qlib sandbox blobs under `Output/benchmarks/market_feedback/` (with explicit `!` exceptions for small governance JSON)

**Do not list:**

- Active source under `packages/`
- Compatibility symlinks — bootstrap recreates them; they may appear untracked locally and that is fine

### Package-local `.gitignore` files

Each package keeps its **own** `.gitignore` for package-local generated content.
Workspace truth for cross-module artifacts remains **`Data/` and `Output/` at
workspace root**, never committed.

---

## Developer workflows

### First clone

```bash
git clone git@github.com:xubo15384751795-sys/system-workspace.git System
cd System
./scripts/bootstrap.sh    # symlinks + venv hints
```

### Research lane (required for nonlinear / long-running topics)

```bash
# From a clean main-based production checkout:
git fetch origin
git worktree add ../System-research research/<topic>
# Develop only inside ../System-research; commit per WP close.
# Merge infrastructure back to main when green; promote conclusions via board + routing decision.
```

### Committing

1. Keep the production directory on `main`.
2. Commit research work on `research/<topic>` inside its worktree.
3. Fast-forward merge green research commits into `main` — do not leave the
   production checkout on a research branch.

Never commit secrets, `Data/`, or `Output/` blobs.

---

## Bootstrap responsibilities

`scripts/bootstrap.sh` must:

1. Recreate compatibility symlinks (`Structural Risk Harvester`, `System Learning Hub`, `Structural Research Harness`, `contracts`)
2. Print per-package venv install hints
3. Optionally sync legacy submodule metadata if still present

Bootstrap does **not** create or populate `Data/` / `Output/`.

---

## Verification

After any git-layout change:

```bash
./scripts/bootstrap.sh
python3 -m pytest tests/ -q
python3 scripts/daily_run.py --dry-run
git branch --show-current   # production checkout must print: main
```

Expected: tests green, dry-run lists the daily sequence, production checkout stays on `main`.
