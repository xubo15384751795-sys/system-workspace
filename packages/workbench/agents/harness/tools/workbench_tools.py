"""workbench_tools — governed Workbench user-facing artifact tools."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.registry import ToolResult, ToolSpec, _register


HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
WORKBENCH_SRC = WORKBENCH_ROOT / "src"
def _resolve_system_root(workbench_root: Path) -> Path:
    """Repo root for both legacy `Workbench/` and `packages/workbench` layouts."""
    parent = workbench_root.parent
    if workbench_root.name.lower() == "workbench" and parent.name == "packages":
        return parent.parent
    return parent

SYSTEM_ROOT = _resolve_system_root(WORKBENCH_ROOT)


def _current_module():
    if str(WORKBENCH_SRC) not in sys.path:
        sys.path.insert(0, str(WORKBENCH_SRC))
    from workbench import current

    return current


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKBENCH_ROOT))
    except ValueError:
        return str(path.resolve())


def _snapshot_current(current_dir: Path) -> dict[str, dict[str, Any]]:
    if not current_dir.exists():
        return {}
    snapshot: dict[str, dict[str, Any]] = {}
    for path in sorted(current_dir.iterdir()):
        stat = path.lstat()
        target = path.resolve() if path.exists() else None
        snapshot[path.name] = {
            "path": _rel(path),
            "is_symlink": path.is_symlink(),
            "resolved_path": _rel(target) if target else None,
            "mtime_ns": stat.st_mtime_ns,
            "bytes": stat.st_size,
        }
    return snapshot


def _change_summary(
    before: dict[str, dict[str, Any]],
    after: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    before_names = set(before)
    after_names = set(after)
    changed = [
        name
        for name in sorted(before_names & after_names)
        if before[name] != after[name]
    ]
    return {
        "created": sorted(after_names - before_names),
        "removed": sorted(before_names - after_names),
        "changed": changed,
        "unchanged": sorted((before_names & after_names) - set(changed)),
    }


def _h_refresh_current(input: dict, dry_run: bool) -> ToolResult:
    current = _current_module()
    before = _snapshot_current(current.CURRENT)
    refresh_script = SYSTEM_ROOT / "scripts" / "refresh_output_current.py"
    proc = subprocess.run(
        [sys.executable, str(refresh_script)],
        cwd=SYSTEM_ROOT,
        text=True,
        capture_output=True,
        timeout=300,
    )
    if proc.returncode != 0:
        return ToolResult(
            ok=False,
            tool_id="workbench.refresh_current",
            summary="Output/current refresh failed",
            artifacts=[],
            evidence={"current_refresh": {"current_path": "Output/current"}},
            errors=[proc.stderr[-1000:] or proc.stdout[-1000:] or "refresh_output_current failed"],
        )
    after = _snapshot_current(current.CURRENT)
    changes = _change_summary(before, after)

    required = [
        "00_READ_ME_FIRST.md",
        "framework_output.json",
    ]
    missing = [name for name in required if name not in after]

    evidence = {
        "current_refresh": {
            "current_path": "Output/current",
            "changes": changes,
            "required_artifacts": {
                name: {"exists": name in after, **after.get(name, {})}
                for name in required
            },
        }
    }
    return ToolResult(
        ok=not missing,
        tool_id="workbench.refresh_current",
        summary=(
            "Refreshed Output/current "
            f"({len(changes['created'])} created, {len(changes['changed'])} changed)"
        ),
        artifacts=[f"Output/current/{name}" for name in sorted(after)],
        evidence=evidence,
        errors=[f"missing current artifact: {name}" for name in missing],
    )


_register(ToolSpec(
    id="workbench.refresh_current",
    description=(
        "Refresh Output/current user-facing pointers and contract artifacts "
        "from the latest framework and learning outputs"
    ),
    subsystem="workbench",
    risk_level="medium",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=False,
    allowed_modes=["run", "edit"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_refresh_current,
))


def _h_run_pipeline_step(input: dict, dry_run: bool) -> ToolResult:
    step_id = str(input.get("step_id") or input.get("step") or "").strip()
    positional = input.get("positional_args", [])
    if not step_id and isinstance(positional, list) and positional:
        step_id = str(positional[0]).strip()
    if not step_id:
        return ToolResult(
            ok=False,
            tool_id="workbench.run_pipeline_step",
            errors=["workbench.run_pipeline_step requires step_id=<registry_step>"],
        )

    mode = str(input.get("mode") or "auto")
    run_script = SYSTEM_ROOT / "scripts" / "run_pipeline_step.py"
    cmd = [sys.executable, str(run_script), "run"]
    if dry_run or str(input.get("dry_run", "false")).lower() in ("true", "1", "yes"):
        cmd.append("--dry-run")
    cmd.append(step_id)
    if mode != "auto":
        cmd.extend(["--mode", mode])
    cmd.append("--json")

    proc = subprocess.run(cmd, cwd=SYSTEM_ROOT, text=True, capture_output=True, timeout=600)
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw_stdout": proc.stdout[-1000:], "raw_stderr": proc.stderr[-1000:]}

    ok = proc.returncode == 0 and payload.get("status", "success") == "success"
    if dry_run:
        ok = proc.returncode == 0
    return ToolResult(
        ok=ok,
        tool_id="workbench.run_pipeline_step",
        summary=f"Pipeline step {step_id}: {payload.get('status', 'unknown')}",
        evidence={"pipeline_step": payload},
        errors=[proc.stderr[-1000:]] if proc.returncode != 0 and proc.stderr else [],
    )


_register(ToolSpec(
    id="workbench.run_pipeline_step",
    description="Execute one daily pipeline registry step via governed runner",
    subsystem="workbench",
    risk_level="medium",
    read_only=False,
    mutates_artifacts=True,
    requires_approval=False,
    allowed_modes=["run", "edit", "verify"],
    required_prechecks=[],
    postchecks=["write_event"],
    handler=_h_run_pipeline_step,
))
