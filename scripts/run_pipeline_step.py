#!/usr/bin/env python3
"""Run a single daily pipeline step by registry id.

Usage:
    python3 scripts/run_pipeline_step.py list
    python3 scripts/run_pipeline_step.py describe judgment_layer
    python3 scripts/run_pipeline_step.py run evidence_grade_report
    python3 scripts/run_pipeline_step.py run judgment_layer --mode auto --json

Also invoked as: system run <step_id> (Workbench harness).
"""
from __future__ import annotations

import argparse
import json
import sys



from scripts._pipeline_runner import (  # noqa: E402
    describe_registry_step,
    list_registry_steps,
    run_registry_step,
)


def _cmd_list(args: argparse.Namespace) -> int:
    steps = list_registry_steps(include_inactive=args.all)
    if args.json:
        print(json.dumps({"count": len(steps), "steps": steps}, indent=2))
        return 0
    print(f"{'ORDER':>5}  {'STEP_ID':<28} {'OWNER':<18} {'MODE':<10} CJ?")
    print("-" * 72)
    for step in steps:
        cj = "yes" if step["affects_core_judgment"] else "no"
        print(
            f"{step['order']:>5}  {step['step_id']:<28} "
            f"{step['owner'][:18]:<18} {step['execution_mode']:<10} {cj}"
        )
    print(f"\n{len(steps)} step(s)")
    return 0


def _cmd_describe(args: argparse.Namespace) -> int:
    detail = describe_registry_step(args.step_id)
    if detail is None:
        print(f"Unknown step: {args.step_id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(detail, indent=2))
        return 0
    print(f"Step: {detail['step_id']}")
    print(f"  Owner: {detail.get('owner')}")
    print(f"  Status: {detail.get('status')}")
    print(f"  Command: {detail.get('command')}")
    print(f"  Affects core judgment: {detail.get('affects_core_judgment')}")
    print(f"  Execution: {detail.get('execution', {}).get('mode', 'subprocess')}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    detail = describe_registry_step(args.step_id)
    if detail is None:
        print(f"Unknown step: {args.step_id}", file=sys.stderr)
        return 1
    if detail.get("status") == "inactive":
        print(f"Step {args.step_id} is inactive", file=sys.stderr)
        return 1

    mode = args.mode
    if mode == "auto":
        mode = None

    if args.dry_run:
        execution = detail.get("execution", {})
        payload = {
            "step_id": args.step_id,
            "dry_run": True,
            "mode": mode or execution.get("mode", "subprocess"),
            "command": detail.get("command"),
            "callable": execution.get("future_callable"),
            "affects_core_judgment": detail.get("affects_core_judgment"),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[dry-run] would run {args.step_id} ({payload['mode']})")
            print(f"  command: {payload['command']}")
        return 0

    result = run_registry_step(args.step_id, mode=mode, argv=args.argv or None)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['step']}: {result['status']} ({result.get('mode', '?')}, {result.get('duration_s', 0)}s)")
        if result.get("stderr_tail"):
            print(result["stderr_tail"], file=sys.stderr)
    return 0 if result.get("status") == "success" else 1


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    use_json = "--json" in raw
    clean = [arg for arg in raw if arg != "--json"]

    parser = argparse.ArgumentParser(description="Run a single daily pipeline registry step.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="List registry steps")
    list_parser.add_argument("--all", action="store_true", help="Include inactive steps")

    describe_parser = sub.add_parser("describe", help="Describe one registry step")
    describe_parser.add_argument("step_id")

    run_parser = sub.add_parser("run", help="Execute one registry step")
    run_parser.add_argument(
        "--mode",
        choices=["auto", "subprocess", "callable"],
        default="auto",
        help="Execution mode (default: registry setting)",
    )
    run_parser.add_argument("--dry-run", action="store_true", help="Show plan without executing")
    run_parser.add_argument("step_id")
    run_parser.add_argument("argv", nargs=argparse.REMAINDER, help="Extra args passed to the step")

    args = parser.parse_args(clean)
    args.json = use_json
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "describe":
        return _cmd_describe(args)
    if args.command == "run":
        if args.argv and args.argv[0] == "--":
            args.argv = args.argv[1:]
        return _cmd_run(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
