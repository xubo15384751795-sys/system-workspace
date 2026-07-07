from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from system_learning.cartography.runner import run_cartography
from system_learning.governance.verify import verify_improvement_lifecycle
from system_learning.ledger.store import read_existing_improvement_queue
from system_learning.ml_integrity import run_pollution_check
from system_learning.runtime.context import new_run_context
from system_learning.runtime.manifest import read_last_run_id
from system_learning.runtime.paths import HubPaths
from system_learning.runtime.pipeline import PipelinePlan, execute_pipeline

SUBCOMMANDS = frozenset(
    {
        "run",
        "record",
        "scan-codebase",
        "check-ml-integrity",
        "verify-lifecycle",
        "rebuild-ledger",
        "replay",
        "governance-audit",
        "research-posture",
    }
)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    if not argv or argv[0] not in SUBCOMMANDS:
        argv = ["run", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "run": _cmd_run,
        "record": _cmd_record,
        "scan-codebase": _cmd_scan_codebase,
        "check-ml-integrity": _cmd_check_ml_integrity,
        "verify-lifecycle": _cmd_verify_lifecycle,
        "rebuild-ledger": _cmd_rebuild_ledger,
        "replay": _cmd_replay,
        "governance-audit": _cmd_governance_audit,
        "research-posture": _cmd_research_posture,
    }
    return handlers[args.command](args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="System Learning Hub governance runtime (orchestration only).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--system-root", type=Path, default=Path("/Users/a1/System"))

    run = sub.add_parser("run", parents=[common], help="Default pipeline: ingest runtime log → ledger → reports.")
    run.add_argument("--ledger-dir", type=Path)
    run.add_argument("--report-dir", type=Path)
    run.add_argument("--run-id", type=str, default=None, help="Explicit hub run id (default: generated).")
    run.add_argument("--since", type=str, default=None, help="Only ingest events with timestamp >= this ISO value.")
    run.add_argument("--with-cartography", action="store_true", help="Run Hub codebase scan before ingest.")
    run.add_argument("--with-ml-integrity", action="store_true", help="Run Hub ML pollution check before ingest.")
    run.add_argument("--cartography-only", action="store_true", help="Run only the codebase scan.")
    run.add_argument("--skip-reports", action="store_true")
    run.add_argument("--no-refresh", action="store_true")

    record = sub.add_parser("record", parents=[common], help="Append one runtime log record (sole peer write path).")
    record.add_argument("--subsystem", required=True)
    record.add_argument("--event-type", required=True)
    record.add_argument("--severity", default="info")
    record.add_argument("--source-tool", default="")
    record.add_argument("--run-id", default="")
    record.add_argument("--payload-json", default="{}")
    record.add_argument("--json", dest="json_blob", default="", help="Full record JSON (overrides field flags).")

    scan = sub.add_parser("scan-codebase", parents=[common], help="Hub codebase scan only.")
    scan.add_argument("--scan-root", type=Path, default=None)
    scan.add_argument("--project-root", type=Path, default=None)

    ml = sub.add_parser("check-ml-integrity", parents=[common], help="Hub ML integrity scan only.")
    ml.add_argument("--raise-on-red", action="store_true")

    ga = sub.add_parser(
        "governance-audit",
        parents=[common],
        help="Run governance guards over the live daily surface (contamination/reality/staleness).",
    )
    ga.add_argument("--registry", type=Path, default=None, help="Override governance registry path.")
    ga.add_argument("--raise-on-block", action="store_true", help="Exit non-zero on a block-severity finding.")

    rp = sub.add_parser(
        "research-posture",
        parents=[common],
        help="Render the confidence-graded research posture digest from the registry.",
    )
    rp.add_argument("--registry", type=Path, default=None, help="Override governance registry path.")

    for name in ("verify-lifecycle", "rebuild-ledger", "replay"):
        cmd = sub.add_parser(name, parents=[common], help=f"Hub runtime: {name}.")
        cmd.add_argument("--ledger-dir", type=Path)
        cmd.add_argument("--report-dir", type=Path)

    replay = sub.choices["replay"]
    replay.add_argument("--from", dest="since", type=str, default=None, metavar="ISO_TIMESTAMP")
    replay.add_argument("--run-id", type=str, default=None)
    replay.add_argument("--with-cartography", action="store_true")
    replay.add_argument("--with-ml-integrity", action="store_true")

    rebuild = sub.choices["rebuild-ledger"]
    rebuild.add_argument("--run-id", type=str, default=None)
    rebuild.add_argument("--skip-reports", action="store_true")

    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    if args.cartography_only:
        return _cmd_scan_codebase(args)

    paths = HubPaths.resolve(args.system_root, ledger_dir=args.ledger_dir, report_dir=args.report_dir)
    context = new_run_context(mode="full", run_id=args.run_id)
    plan = PipelinePlan(
        run_cartography=args.with_cartography,
        run_ml_integrity=args.with_ml_integrity,
        collect_events=True,
        write_reports=not args.skip_reports,
        events_since=args.since,
    )
    result = execute_pipeline(context, paths, plan)
    _print_pipeline_result(result)
    if not args.no_refresh:
        _refresh_output_current(paths.system_root)
    return 0


def _cmd_record(args: argparse.Namespace) -> int:
    import json

    from system_learning.runtime.record import append_runtime_record

    if args.json_blob:
        try:
            record = json.loads(args.json_blob)
        except json.JSONDecodeError as exc:
            print(f"Invalid --json: {exc}", file=sys.stderr)
            return 1
        if not isinstance(record, dict):
            print("--json must decode to an object", file=sys.stderr)
            return 1
    else:
        try:
            extra = json.loads(args.payload_json)
        except json.JSONDecodeError as exc:
            print(f"Invalid --payload-json: {exc}", file=sys.stderr)
            return 1
        if not isinstance(extra, dict):
            print("--payload-json must decode to an object", file=sys.stderr)
            return 1
        record = {
            "subsystem": args.subsystem,
            "event_type": args.event_type,
            "severity": args.severity,
            "source_tool": args.source_tool or args.subsystem,
            "run_id": args.run_id,
            **extra,
        }
    path = append_runtime_record(args.system_root.resolve(), record)
    print(path)
    return 0


def _cmd_scan_codebase(args: argparse.Namespace) -> int:
    paths = HubPaths.resolve(args.system_root)
    scan_root = (args.scan_root or paths.system_root).resolve()
    project_root = (args.project_root or paths.hub_project_root).resolve()
    outputs = run_cartography(scan_root=scan_root, project_root=project_root)
    print(f"Codebase scan completed under {scan_root}.")
    for name, path in outputs.items():
        print(f"  {name}: {path}")
    return 0


def _cmd_check_ml_integrity(args: argparse.Namespace) -> int:
    paths = HubPaths.resolve(args.system_root)
    report = run_pollution_check(
        signals_root=paths.system_root / "Output" / "ml_signals",
        runs_root=paths.system_root / "Output" / "deformation_runs",
        events_dir=paths.events_dir,
        raise_on_red=args.raise_on_red,
    )
    print(
        f"ML pollution check: passed={report.passed} "
        f"red={len(report.red_violations)} amber={len(report.amber_violations)}"
    )
    return 0 if report.passed else 1


def _cmd_verify_lifecycle(args: argparse.Namespace) -> int:
    paths = HubPaths.resolve(args.system_root, ledger_dir=args.ledger_dir)
    import pandas as pd

    queue = read_existing_improvement_queue(paths.ledger_dir)
    report = verify_improvement_lifecycle(queue if queue is not None else pd.DataFrame())
    print(f"Lifecycle verification: ok={report['ok']} items={report['item_count']} issues={len(report['issues'])}")
    for issue in report["issues"]:
        print(f"  - {issue['improvement_id']}: {issue['kind']} — {issue['detail']}")
    return 0 if report["ok"] else 1


def _cmd_rebuild_ledger(args: argparse.Namespace) -> int:
    paths = HubPaths.resolve(args.system_root, ledger_dir=args.ledger_dir, report_dir=args.report_dir)
    context = new_run_context(mode="rebuild-ledger", run_id=args.run_id)
    plan = PipelinePlan(
        collect_events=False,
        write_reports=not args.skip_reports,
    )
    result = execute_pipeline(context, paths, plan)
    _print_pipeline_result(result)
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    paths = HubPaths.resolve(args.system_root, ledger_dir=args.ledger_dir, report_dir=args.report_dir)
    context = new_run_context(mode="replay", run_id=args.run_id)
    plan = PipelinePlan(
        run_cartography=args.with_cartography,
        run_ml_integrity=args.with_ml_integrity,
        collect_events=True,
        write_reports=True,
        events_since=args.since,
    )
    result = execute_pipeline(context, paths, plan)
    _print_pipeline_result(result)
    last = read_last_run_id(paths.runs_dir)
    if last and last != context.run_id:
        print(f"Previous run id: {last}")
    return 0


def _cmd_governance_audit(args: argparse.Namespace) -> int:
    from system_learning.guards import run_governance_audit, write_report
    from system_learning.guards.audit import REPORT_DIR_RELPATH

    system_root = args.system_root.resolve()
    report = run_governance_audit(system_root, registry_path=args.registry)
    paths = write_report(report, system_root / REPORT_DIR_RELPATH)

    print(
        f"governance-audit: ok={report.ok} "
        f"passed={len(report.passed_guards)} failed={len(report.failed_guards)}"
    )
    for f in report.findings:
        print(f"  [{f.severity}] {f.guard}: {f.entity} — {f.detail}")
    for name, path in paths.items():
        print(f"  report.{name}: {path}")

    return 1 if (not report.ok and args.raise_on_block) else 0


def _cmd_research_posture(args: argparse.Namespace) -> int:
    from system_learning.guards import run_research_posture

    system_root = args.system_root.resolve()
    digest, paths = run_research_posture(system_root, registry_path=args.registry)
    print(f"research-posture: overall={digest.overall_posture} ({digest.overall_reason})")
    print(f"  entries: {len(digest.entries)}")
    for name, path in paths.items():
        print(f"  report.{name}: {path}")
    return 0


def _print_pipeline_result(result) -> None:
    print(f"run_id: {result.context.run_id}")
    print(f"mode: {result.context.mode}")
    print(f"steps: {' → '.join(result.steps_completed)}")
    print(f"events: {len(result.events)}")
    for name, path in result.ledger_paths.items():
        print(f"ledger.{name}: {path}")
    for name, path in result.report_paths.items():
        print(f"report.{name}: {path}")
    if result.manifest_path:
        print(f"manifest: {result.manifest_path}")


def _refresh_output_current(system_root: Path) -> None:
    refresh_script = system_root / "scripts" / "refresh_output_current.py"
    if not refresh_script.exists():
        print("Run:")
        print(f"  {system_root / 'sys'} refresh")
        return
    try:
        subprocess.run(["python3", str(refresh_script)], check=True)
    except Exception as exc:
        print(f"Warning: could not refresh Output/current: {exc}")
        print("Try:")
        print(f"  {system_root / 'sys'} refresh")
