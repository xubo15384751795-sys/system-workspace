# Git Workspace Policy

**Status:** authoritative as of 2026-05-22  
**Supersedes:** ad-hoc "nested clone vs submodule vs move under Workbench" options in older audit notes.

This is the single policy for how source code is versioned in `system-workspace`.
Path layout is in `governance/repo_layout_map.md`; directory ownership is in
`FOLDER_OWNERSHIP.md`.

---

## Decision (locked)

| Topic | Policy |
|---|---|
| Layout | **Sibling directories at workspace root** — no physical nest under `Workbench/data_providers/` or `Workbench/governance/` |
| Versioning | **Git submodules** for all four sister repos; parent records pinned commits in `.gitmodules` |
| Fresh checkout | `git clone --recurse-submodules` **or** `git clone` + `./scripts/bootstrap.sh` |
| Generated data | **Never committed** in any repo — `Data/` and `Output/` stay gitignored at workspace root |
| Compatibility symlinks | Recreated by `scripts/bootstrap.sh`; not submodule paths |

Retired options (do not reopen without an explicit migration plan):

- **2a** — move harvester/hub under `Workbench/` (deferred indefinitely; high breakage risk)
- **Bootstrap-only clone** — sister repos gitignored with no `.gitmodules` (inconsistent; replaced by submodules)

---

## Repository map

| Submodule path | Remote repo | Role |
|---|---|---|
| `Workbench/` | `structural-workbench` | Product, NLP, contracts, agent harness |
| `Structural Deformation Research System/` | `Structural-Deformation-Research-System` | Deformation framework core |
| `structural-risk-harvester/` | `structural-risk-harvester` | Data provider / harvester |
| `system-learning-hub/` | `system-learning-hub` | Governance memory tool |

Parent repo (`system-workspace`) owns:

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

- Submodule directories (`Workbench/`, `structural-risk-harvester/`, `system-learning-hub/`, `Structural Deformation Research System/`) — Git tracks these as gitlinks via `.gitmodules`
- Compatibility symlinks — bootstrap recreates them; they may appear untracked locally and that is fine

### Sister repo `.gitignore` files

Each submodule keeps its **own** `.gitignore` for repo-local generated content:

| Repo | Ignores locally |
|---|---|
| `Workbench/` | `Data/` (Workbench-local scratch) |
| `structural-risk-harvester/` | `data/` symlink target volume |
| `system-learning-hub/` | `/data/`, `/reports/` at repo root |
| `Structural Deformation Research System/` | framework-local outputs (see that repo's `.gitignore`) |

Workspace truth for cross-module artifacts remains **`Data/` and `Output/` at workspace root**, never committed.

---

## Developer workflows

### First clone

```bash
git clone --recurse-submodules git@github.com:xubo15384751795-sys/system-workspace.git System
cd System
./scripts/bootstrap.sh    # symlinks + submodule sync + venv hints
```

Without `--recurse-submodules`:

```bash
git clone git@github.com:xubo15384751795-sys/system-workspace.git System
cd System
./scripts/bootstrap.sh    # runs git submodule update --init --recursive
```

### Update sister repos

```bash
git submodule update --remote --merge   # advance pins deliberately
# or enter a submodule and pull on a branch, then commit the new gitlink in parent
```

### Committing cross-repo work

1. Commit inside the submodule on its branch.
2. Push the submodule repo.
3. Commit the updated gitlink in `system-workspace`.
4. Push the parent.

Never commit sister-repo source files directly into the parent tree.

---

## Bootstrap responsibilities

`scripts/bootstrap.sh` must:

1. `git submodule update --init --recursive` (fallback: clone if submodule metadata missing during migration)
2. Recreate compatibility symlinks (`Structural Risk Harvester`, `System Learning Hub`, `Structural Research Harness`, `contracts`)
3. Print per-repo venv install hints

Bootstrap does **not** create or populate `Data/` / `Output/`.

---

## Verification

After any git-layout change:

```bash
test -f .gitmodules && git submodule status
./scripts/bootstrap.sh
pytest tests/governance/ -q
```

Expected: four submodule entries, symlinks resolve, governance tests pass.
