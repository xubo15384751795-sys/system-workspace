"""system — fast-path dispatcher for Structural Research Harness.

--version        never imports pandas, JAX, Diffrax, or providers.
inspect-*       reads JSON / manifest / catalog with stdlib only.
fetch / run / analyze   dynamically import heavy subsystems on demand.

Tool Registry commands:
  system tools list [--mode MODE]      List registered tools
  system tools run TOOL_ID [KWARGS]    Run a tool via registry
  system tools get TOOL_ID             Show tool metadata
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
VERSION_PATH = HARNESS_ROOT / "VERSION"

if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

# Sub-command modules are imported only after dispatch — never at module level.
# This keeps ``system --version`` fast (< 200 ms).


def _read_version() -> str:
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def _print_help(file=None):
    print(
        "system — Structural Research Harness\n"
        "\n"
        "Usage:\n"
        "  system --version                       Show harness version\n"
        "  system --help                          This help\n"
        "\n"
        "  system harvester list-releases         List all finalized data releases\n"
        "  system harvester inspect-release ID    Inspect a release catalog\n"
        "\n"
        "  system deformation list-snapshots      List all deformation snapshots\n"
        "  system deformation inspect-snapshot ID Inspect a snapshot\n"
        "\n"
        "  system learning-hub inspect-queue      Show improvement queue\n"
        "  system learning-hub inspect-health     Show subsystem health report\n"
        "\n"
        "  system run list                        List daily pipeline registry steps\n"
        "  system run STEP_ID                     Run one pipeline step by registry id\n"
        "  system run describe STEP_ID            Show step metadata\n"
        "\n"
        "  system tools list [--mode MODE]        List registered tools\n"
        "  system tools run TOOL_ID [KWARGS]      Run a tool via registry\n"
        "  system tools get TOOL_ID               Show tool metadata\n"
        "\n"
        "Flags:\n"
        "  --json    Machine-readable JSON output\n"
        "\n"
        "Exit codes:  0 success  1 runtime error  2 bad arguments",
        file=file,
    )


def _parse_extra_kwargs(rest: list[str]) -> dict:
    """Parse key=value pairs from remaining CLI args into a dict."""
    result: dict = {}
    for arg in rest:
        if "=" in arg:
            k, v = arg.split("=", 1)
            result[k] = v
    return result


def _cmd_tools(args: list[str]) -> int:
    """Handle ``system tools ...`` sub-commands."""
    # Ensure the harness root is on sys.path so we can import tools.*
    if str(HARNESS_ROOT) not in sys.path:
        sys.path.insert(0, str(HARNESS_ROOT))
    import tools.artifact_tools      # noqa: F401 — side-effect: registers tools
    import tools.protocol_tools      # noqa: F401 — side-effect: registers tools
    import tools.routing_tools       # noqa: F401 — side-effect: registers tools
    import tools.harvester_tools      # noqa: F401 — side-effect: registers tools
    import tools.deformation_tools    # noqa: F401
    import tools.learning_hub_tools   # noqa: F401
    import tools.workbench_tools      # noqa: F401
    from tools.registry import list_tools, get_tool, run_tool

    if not args:
        print("system tools: sub-command required: list | run | get", file=sys.stderr)
        return 2

    cmd, *rest = args
    use_json = "--json" in rest
    clean = [a for a in rest if a != "--json"]

    # extract --mode MODE
    mode = "explore"
    for i, a in enumerate(clean):
        if a == "--mode" and i + 1 < len(clean):
            mode = clean[i + 1]
            clean = clean[:i] + clean[i + 2:]
            break

    if cmd == "list":
        tools = list_tools(mode=mode)
        if use_json:
            result = [
                {
                    "id": t.id,
                    "description": t.description,
                    "subsystem": t.subsystem,
                    "risk_level": t.risk_level,
                    "read_only": t.read_only,
                    "mutates_artifacts": t.mutates_artifacts,
                    "requires_approval": t.requires_approval,
                    "allowed_modes": t.allowed_modes,
                    "required_prechecks": t.required_prechecks,
                    "postchecks": t.postchecks,
                }
                for t in tools
            ]
            print(json.dumps({"status": "ok", "mode": mode, "count": len(result), "tools": result}, indent=2))
            return 0
        if not tools:
            print(f"No tools registered for mode '{mode}'.")
            return 0
        print(f"{'TOOL ID':<44} {'SUBSYS':<14} {'MODE':<10} {'READ':<6} {'MUT':<5} {'RISK':<7}")
        print("-" * 92)
        for t in tools:
            modes = ",".join(t.allowed_modes)
            print(f"{t.id:<44} {t.subsystem:<14} {modes:<10} {str(t.read_only):<6} {str(t.mutates_artifacts):<5} {t.risk_level:<7}")
        print(f"\n{len(tools)} tool(s) in mode '{mode}'")
        return 0

    if cmd == "get":
        if not clean:
            print("system tools: get requires a TOOL_ID", file=sys.stderr)
            return 2
        tool_id = clean[0]
        spec = get_tool(tool_id)
        if spec is None:
            print(f"system tools: unknown tool '{tool_id}'", file=sys.stderr)
            return 1
        if use_json:
            print(json.dumps({
                "id": spec.id,
                "description": spec.description,
                "subsystem": spec.subsystem,
                "risk_level": spec.risk_level,
                "read_only": spec.read_only,
                "mutates_artifacts": spec.mutates_artifacts,
                "requires_approval": spec.requires_approval,
                "allowed_modes": spec.allowed_modes,
                "required_prechecks": spec.required_prechecks,
                "postchecks": spec.postchecks,
            }, indent=2))
            return 0
        print(f"Tool:       {spec.id}")
        print(f"Subsystem:  {spec.subsystem}")
        print(f"Risk:       {spec.risk_level}")
        print(f"Read-only:  {spec.read_only}")
        print(f"Mutates:    {spec.mutates_artifacts}")
        print(f"Approval:   {spec.requires_approval}")
        print(f"Modes:      {', '.join(spec.allowed_modes)}")
        print(f"Prechecks:  {spec.required_prechecks or '[]'}")
        print(f"Postchecks: {spec.postchecks or '[]'}")
        print(f"Desc:       {spec.description}")
        return 0

    if cmd == "run":
        if not clean:
            print("system tools: run requires a TOOL_ID", file=sys.stderr)
            return 2
        tool_id = clean[0]
        kwargs = _parse_extra_kwargs(clean[1:])
        # Add any positional args as input keys
        pos = [a for a in clean[1:] if "=" not in a]
        if pos:
            kwargs["positional_args"] = pos
        dry_run = kwargs.pop("dry_run", "false").lower() in ("true", "1", "yes")
        result = run_tool(tool_id, kwargs, mode=mode, dry_run=dry_run)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1

    print(f"system tools: unknown sub-command '{cmd}'", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    if not args:
        _print_help()
        return 0

    head = args[0]

    # --version: no imports beyond stdlib
    if head == "--version":
        print(f"system-harness {_read_version()}")
        return 0

    if head in ("--help", "-h"):
        _print_help()
        return 0

    # Dispatch to sub-CLI
    tail = args[1:]

    if head == "harvester":
        from entrypoints.harvester_cli import main as sub
        return sub(tail)

    if head == "deformation":
        from entrypoints.deformation_cli import main as sub
        return sub(tail)

    if head == "learning-hub":
        from entrypoints.learning_hub_cli import main as sub
        return sub(tail)

    if head == "run":
        from entrypoints.run_cli import main as sub
        return sub(tail)

    if head == "tools":
        return _cmd_tools(tail)

    print(f"system: unknown subcommand '{head}'", file=sys.stderr)
    _print_help(file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
