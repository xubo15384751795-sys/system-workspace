# GitHub Publishing Plan

This workspace is not a single ordinary project. It is a system workspace that contains multiple publishable codebases, shared data/output areas, symlinks, and local tooling state.

## Recommended Repository Shape

Publish code as separate repositories instead of pushing the whole `/Users/a1/System` folder as one GitHub repo.

1. `Structural Deformation Research System`
   - Primary research/application codebase.
   - Already has its own `.git`.
   - Good candidate for the main private GitHub repository.

2. `Workbench/data_providers/structural-risk-harvester`
   - Data harvester/provider codebase.
   - Already has its own `.git`.
   - Good candidate for a separate private GitHub repository.

3. Workspace shell docs and orchestration
   - Root-level docs such as `README.md`, `FOLDER_OWNERSHIP.md`, `WORKBENCH_SPEC.md`, `protocols/`, `configs/`, and `sys`.
   - If these need GitHub history, publish them as a lightweight coordination repository, without `Data/`, `Output/`, virtual environments, local assistant configs, or generated caches.

## Keep Out of GitHub

Never commit:

- `Data/`
- `Output/`
- `OpenBB/venv/`
- real env files such as `OpenBB/settings.env`
- `.claude/`
- `.idea/`
- `.pytest_cache/`, `.ruff_cache/`, `.cache/`
- `__pycache__/`, `*.pyc`
- `.DS_Store`
- `*.duckdb`, `*.parquet`, logs, and other generated binary artifacts

Commit example files instead:

- `*.env.example`
- small schemas, manifests, and documentation that explain how generated data is produced

## Push Workflow

For each repository:

1. Review ignored files before staging.
2. Stage intentionally by area, not with blind all-file commits.
3. Run `python3 scripts/github_preflight.py` from the workspace root.
4. Run the relevant test set for that repo.
5. Commit small logical chunks.
6. Push to a private GitHub repo first.
7. Use GitHub secret scanning and keep branch protection on the main branch.

## Practical First Push Order

1. Push `Workbench/data_providers/structural-risk-harvester` first if other projects depend on its data contracts.
2. Push `Structural Deformation Research System` second.
3. Add the root coordination repository only after the two code repos are clean and understandable.
