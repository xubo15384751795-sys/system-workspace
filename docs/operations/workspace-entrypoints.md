# Workspace entrypoints

Operator loop for Verity lives in the root README:

```bash
./sys check
./sys open
./sys next
./sys roadmap
```

This page lists additional maintainer commands. None of them grant
publication authority.

## Status and navigation

```bash
python3 scripts/system_status.py        # one-screen workspace digest
python3 scripts/list_latest.py          # resolved latest paths per subsystem
python3 scripts/build_system_index.py   # regenerate Data/system_index/
./sys current                           # user-facing run cockpit
./sys evidence                          # benchmark + evidence dashboard
./sys artifacts                         # report artifact navigator
```

Always resolve `latest` through `find -L` or `realpath`. Treating a symlink as
an empty directory is a recorded boundary violation.

## Promotion and publication

```bash
python3 scripts/promote_snapshot.py --run <run_id>
```

`promote_snapshot.py` canonicalises a framework snapshot into
`Data/deformation/snapshots/`. It is **not** the Current-pointer authority.

Current publication is owned by `system_runtime.publish_admission` and
`system_runtime.publish_transaction`. Only an admitted, committed generation
may change `Output/current`.

## Install and aliases

```bash
uv sync --locked --all-packages
./scripts/bootstrap.sh
```

Bootstrap recreates compatibility aliases. It does not fetch git submodules.
There is no `.gitmodules` file. Layout authority:
[`governance/repo_layout_map.md`](../../governance/repo_layout_map.md).
