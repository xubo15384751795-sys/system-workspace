"""One explicit CLI surface for the System workspace."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from system_runtime.migrations import migrate_known_event_stores
from system_runtime.paths import WorkspacePaths
from system_runtime.pipeline import (
    PipelineSpecError,
    load_pipeline,
    render_sequence_yaml,
    run_step,
)


def _code_root() -> Path:
    """Checkout that contains system_cli + scripts (may differ from data workspace)."""
    return Path(__file__).resolve().parents[1]


def _script_path(paths: WorkspacePaths, relative: str) -> Path:
    """Resolve a repo script for the active workspace.

    Operator workspaces usually coincide with the code checkout. Hermetic tests
    inject a data-only SYSTEM_WORKSPACE_ROOT; scripts still live in the checkout.
    """
    in_workspace = paths.root / relative
    if in_workspace.is_file():
        return in_workspace
    in_code = _code_root() / relative
    if in_code.is_file():
        return in_code
    return in_workspace


def _run(paths: WorkspacePaths, relative: str, args: Sequence[str] = ()) -> int:
    # cwd stays on the workspace so relative writes land in the sandbox/operator root;
    # SYSTEM_WORKSPACE_ROOT (set by --workspace) keeps WorkspacePaths.discover correct.
    result = subprocess.run(
        [sys.executable, str(_script_path(paths, relative)), *args],
        cwd=paths.root,
    )
    return result.returncode


def _show(path: Path, *, lines: int | None = None) -> int:
    if not path.exists():
        print(f"Missing: {path}", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    if lines is not None:
        text = "\n".join(text.splitlines()[:lines]) + "\n"
    print(text, end="" if text.endswith("\n") else "\n")
    return 0


def _pipeline_command(args: argparse.Namespace, paths: WorkspacePaths) -> int:
    pipeline = load_pipeline(paths)
    if args.pipeline_command == "validate":
        print(json.dumps({"valid": True, "steps": len(pipeline.steps), "edges": len(pipeline.edges)}, indent=2))
        return 0
    if args.pipeline_command == "generate":
        target = paths.governance / "daily_run_sequence.yaml"
        rendered = render_sequence_yaml(pipeline)
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != rendered:
                print(f"Generated view is stale: {target}", file=sys.stderr)
                return 1
            print(f"Generated view is current: {target}")
            return 0
        target.write_text(rendered, encoding="utf-8")
        print(f"Generated {target}")
        return 0
    if args.pipeline_command == "list":
        rows = [
            {
                "step_id": step.step_id,
                "order": step.order,
                "schedule": step.schedule,
                "status": step.status,
                "owner": step.owner,
                "mode": step.execution_mode,
            }
            for step in pipeline.steps
            if args.all or step.status not in {"archived", "inactive"}
        ]
        if args.json:
            print(json.dumps({"count": len(rows), "steps": rows}, indent=2))
        else:
            print(f"{'ORDER':>6}  {'STEP':<32} {'SCHEDULE':<10} {'MODE':<10} OWNER")
            for row in rows:
                print(
                    f"{row['order']:>6g}  {row['step_id']:<32} "
                    f"{row['schedule']:<10} {row['mode']:<10} {row['owner']}"
                )
        return 0
    if args.pipeline_command == "describe":
        step = pipeline.step(args.step_id)
        payload = {**step.__dict__, "upstream": list(pipeline.edges.get(step.step_id, ())) }
        print(json.dumps(payload, indent=2))
        return 0
    if args.pipeline_command == "run":
        if args.dry_run:
            step = pipeline.step(args.step_id)
            print(json.dumps({"dry_run": True, **step.__dict__}, indent=2))
            return 0
        result = run_step(args.step_id, argv=args.step_args, mode=args.mode, paths=paths)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "success" else 1
    return 2


def _legacy_command(args: argparse.Namespace, paths: WorkspacePaths) -> int:
    command = args.command
    current = paths.current
    if command in {"check", "current"}:
        return _show(current / "00_READ_ME_FIRST.md", lines=55)
    if command == "refresh":
        for script in (
            "scripts/refresh_output_current.py",
            "scripts/build_artifact_navigator.py",
        ):
            code = _run(paths, script)
            if code:
                return code
        return 0
    if command in {"next", "learning"}:
        return _show(current / "next_actions.md", lines=80)
    if command == "explain":
        path = current / "00_READ_ME_FIRST.md"
        if not path.exists():
            return _show(path)
        text = path.read_text(encoding="utf-8")
        marker = "## Framework Diagnosis"
        section = text[text.find(marker):] if marker in text else text
        print("\n".join(section.splitlines()[:45]))
        return 0
    if command == "ask":
        return _run(paths, "scripts/ask_evidence.py", args.arguments)
    if command == "status":
        return _run(paths, "scripts/system_status.py", args.arguments)
    if command == "governance":
        code = _run(paths, "scripts/commands/weekly/governance_status.py", args.arguments)
        if code == 0:
            return _show(paths.output / "system_learning/latest/governance_status.md", lines=90)
        return code
    if command in {"work", "work-cycle"}:
        extra = ["--mode", "quick"] if command == "work" else list(args.arguments)
        return _run(paths, "scripts/run_work_cycle.py", extra)
    if command == "supervisor":
        return _run(paths, "scripts/run_supervisor_check.py", args.arguments)
    if command == "artifacts":
        return _run(paths, "scripts/build_artifact_navigator.py", args.arguments)
    if command == "evidence":
        code = _run(paths, "scripts/build_benchmark_evidence_dashboard.py", args.arguments)
        if code:
            return code
        markdown = current / "benchmark_evidence_dashboard.md"
        return _show(markdown, lines=80) if markdown.exists() else 0
    if command == "validate-contract":
        return _run(paths, "scripts/validate_workbench_contract.py", args.arguments)
    if command == "framework":
        return _run(paths, "scripts/archive/framework_cli.py", args.arguments)
    if command == "doctor":
        required = [
            current / "00_READ_ME_FIRST.md",
            current / "framework_output.json",
            current / "latest_run_id.txt",
        ]
        missing = [str(path) for path in required if not path.exists()]
        print(json.dumps({"status": "ok" if not missing else "failed", "missing": missing}, indent=2))
        return 1 if missing else 0
    if command == "verify":
        arguments = list(args.arguments)
        if "--control-closure" in arguments:
            return _run(paths, "scripts/verify_control_closure.py", arguments)
        return _run(paths, "scripts/verify_merge.py", arguments)
    if command == "run-daily":
        return _run(paths, "scripts/daily_run.py", args.arguments)
    if command == "report":
        return _show(current / "latest_report.html", lines=20)
    if command == "roadmap":
        return _run(paths, "scripts/roadmap_progress.py", args.arguments)
    raise ValueError(command)


def _state_command(args: argparse.Namespace, paths: WorkspacePaths) -> int:
    result = migrate_known_event_stores(paths, apply=args.state_command == "migrate")
    payload = {
        "mode": args.state_command,
        "files_scanned": result.files_scanned,
        "files_changed": result.files_changed,
        "records_scanned": result.records_scanned,
        "legacy_records": result.legacy_records,
        "backup_root": str(result.backup_root) if result.backup_root else None,
    }
    print(json.dumps(payload, indent=2))
    return 1 if args.state_command == "audit" and result.legacy_records else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="system", description="System research runtime")
    parser.add_argument("--workspace", type=Path, help="Explicit workspace root")
    sub = parser.add_subparsers(dest="command", required=True)

    pipeline = sub.add_parser("pipeline", help="Inspect or execute the compiled pipeline")
    pipeline_sub = pipeline.add_subparsers(dest="pipeline_command", required=True)
    listing = pipeline_sub.add_parser("list")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--json", action="store_true")
    describe = pipeline_sub.add_parser("describe")
    describe.add_argument("step_id")
    run = pipeline_sub.add_parser("run")
    run.add_argument("step_id")
    run.add_argument("step_args", nargs=argparse.REMAINDER)
    run.add_argument("--mode", choices=["subprocess", "callable"])
    run.add_argument("--dry-run", action="store_true")
    pipeline_sub.add_parser("validate")
    generate = pipeline_sub.add_parser("generate", help="Generate compatibility views")
    generate.add_argument("--check", action="store_true", help="Fail if generated view is stale")

    state = sub.add_parser("state", help="Audit or migrate versioned state stores")
    state_sub = state.add_subparsers(dest="state_command", required=True)
    state_sub.add_parser("audit", help="Report legacy records without writing")
    state_sub.add_parser("migrate", help="Back up and migrate known event stores")

    aliases = {
        "check": "Show the current readout",
        "current": "Alias for check",
        "refresh": "Refresh current artifacts",
        "next": "Show next actions",
        "learning": "Alias for next",
        "explain": "Show framework diagnosis",
        "ask": "Ask over current evidence",
        "status": "Show subsystem status",
        "governance": "Show governance status",
        "work": "Run quick work cycle",
        "work-cycle": "Run a work cycle",
        "supervisor": "Run supervisor audit",
        "artifacts": "Build artifact navigator",
        "evidence": "Build evidence dashboard",
        "validate-contract": "Validate a workbench contract",
        "framework": "Manage analysis frameworks",
        "doctor": "Validate current pointers",
        "verify": "Run merge/control verification",
        "run-daily": "Run the daily pipeline",
        "report": "Display the current report path/content",
        "roadmap": "Show evidence-derived validation roadmap progress",
    }
    for name, help_text in aliases.items():
        command = sub.add_parser(name, help=help_text)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.workspace:
        os.environ["SYSTEM_WORKSPACE_ROOT"] = str(args.workspace.resolve())
    try:
        paths = WorkspacePaths.discover()
        if args.command == "pipeline":
            return _pipeline_command(args, paths)
        if args.command == "state":
            return _state_command(args, paths)
        return _legacy_command(args, paths)
    except (PipelineSpecError, KeyError, RuntimeError, ValueError) as exc:
        print(f"system: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
