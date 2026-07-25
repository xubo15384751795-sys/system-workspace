# Branch Protection & Merge Gate (Phase C5)

## Required: configure GitHub branch protection for `main`

The CI workflow (`.github/workflows/ci.yml`) defines a single authoritative
`merge-gate` job that `needs` all other jobs. Branch protection must require
**only** `merge-gate` as a required status check - not the individual
`pre-commit` / `lint` / `workbench` / `integration` jobs (those are already
dependencies of `merge-gate`; requiring them separately allows divergence).

### Settings (GitHub repo → Settings → Branches → Branch protection rules)

- **Branch name pattern:** `main`
- **Require a pull request before merging:** ✓
  - Required approvals: ≥1
  - Dismiss stale approvals on new push: ✓
- **Require status checks to pass before merging:** ✓
  - **Required status checks:** `merge-gate` (ONLY this one)
  - Require branches to be up to date before merging: ✓
- **Require conversation resolution before merging:** ✓
- **Do not allow bypassing the above settings:** ✓ (applies to admins too)
- **Restrict who can push to matching branches:** no one (force PR-only)

### Why only `merge-gate`

`merge-gate` (`.github/workflows/ci.yml` job `merge-gate`) `needs:`
`[pre-commit, lint, workbench, deformation, harvester, hub, integration]`.
Requiring the individual jobs separately lets them be re-run independently and
diverge from the aggregate. Requiring only `merge-gate` makes the AND-aggregate
unbypassable: all 7 upstream jobs must pass for `merge-gate` to even run, and
`merge-gate` itself re-runs `verify_merge.py --merge` (full root pytest + all
package suites + DAG compile + governance freeze + architecture audit +
daily-run dry-run + incident regression) emitting a SHA-bound manifest.

## Local enforcement: pre-push hook

```bash
./scripts/install_pre_push_hook.sh
```

Installs `.git/hooks/pre-push` which runs `./sys verify --merge` on any push
to `main`. Feature-branch pushes are unaffected. This prevents a direct
`git push origin main` from bypassing the gate before it reaches CI.

## The merge-gate command

```bash
./sys verify --merge    # run full gate, emit SHA-bound manifest
./sys verify --check    # check existing manifest validity for current SHA
```

The manifest at `Output/verification/merge_gate_manifest.json` is bound to the
commit SHA. A stale manifest (different SHA) is automatically invalid - the
gate must be re-run after every code change. No required step uses
`continue-on-error` or `|| true`.

## What was removed (Phase C4)

- `weekly-governance.yml`: governance freeze `continue-on-error: true` → binding.
- `nightly.yml`: mypy `|| true` → binding.

The merge path no longer has any advisory-only steps.
