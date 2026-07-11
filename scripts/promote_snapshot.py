from __future__ import annotations

from _workspace_imports import add_workbench_src

add_workbench_src()

from workbench.workspace.promote_snapshot import main

if __name__ == "__main__":
    raise SystemExit(main())
