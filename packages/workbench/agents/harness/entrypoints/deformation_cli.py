"""deformation_cli — fast-path commands for deformation-framework.

list-snapshots / inspect-snapshot  use stdlib JSON + filesystem only.
fetch / run / analyze              dynamically import deformation packages (JAX/Diffrax).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parent.parent
WORKBENCH_ROOT = HARNESS_ROOT.parent.parent
RUNS_ROOT = WORKBENCH_ROOT / "Output" / "deformation_runs"
logger = logging.getLogger(__name__)

HELP = """system deformation — deformation-framework commands

  list-snapshots [--json]              List all deformation snapshots
  inspect-snapshot <id|latest> [--json]  Inspect a snapshot

Exit codes:  0 success  1 runtime error  2 bad arguments"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        print(HELP)
        return 0

    cmd, *rest = args
    use_json = "--json" in rest
    clean = [a for a in rest if a != "--json"]

    if cmd == "list-snapshots":
        return _list_snapshots(json_output=use_json)

    if cmd == "inspect-snapshot":
        if not clean:
            print("deformation: inspect-snapshot requires a snapshot id or 'latest'", file=sys.stderr)
            return 2
        return _inspect_snapshot(clean[0], json_output=use_json)

    print(f"deformation: unknown command '{cmd}'", file=sys.stderr)
    print(HELP, file=sys.stderr)
    return 2


# ── fast-path: stdlib only ─────────────────────────────────────────────

def _resolve_snapshot(snapshot_id: str) -> Path | None:
    if snapshot_id == "latest":
        latest_sym = RUNS_ROOT / "latest"
        if latest_sym.is_symlink():
            return latest_sym.resolve()
        return None
    candidate = RUNS_ROOT / snapshot_id
    return candidate if candidate.is_dir() else None


def _run_dirs() -> list[Path]:
    if not RUNS_ROOT.is_dir():
        return []
    dirs: list[Path] = []
    for p in sorted(RUNS_ROOT.iterdir(), reverse=True):
        if p.is_dir() and not p.is_symlink():
            dirs.append(p)
    return dirs


def _snapshot_json_path(run_dir: Path) -> Path | None:
    """Find the main <run_date>_<run_type>.json file in a run directory."""
    for child in sorted(run_dir.iterdir()):
        if child.suffix == ".json" and child.name not in ("run_manifest.json", "artifacts.json"):
            return child
    # fallback: check data/snapshot.json
    fallback = run_dir / "data" / "snapshot.json"
    if fallback.is_file():
        return fallback
    return None


def _list_snapshots(*, json_output: bool = False) -> int:
    runs = _run_dirs()
    if json_output:
        result = []
        for rd in runs:
            info = {"run_id": rd.name}
            manifest_path = rd / "run_manifest.json"
            if manifest_path.is_file():
                try:
                    m = json.loads(manifest_path.read_text(encoding="utf-8"))
                    info["run_date"] = m.get("run_date", "")
                    info["run_type"] = m.get("run_type", "")
                    info["status"] = m.get("status", "")
                    info["generated_at"] = m.get("generated_at", "")
                except (OSError, json.JSONDecodeError):
                    logger.warning("Unable to read deformation run manifest: %s", manifest_path, exc_info=True)
            result.append(info)
        print(json.dumps({"status": "ok", "snapshots": result}, indent=2))
        return 0

    if not runs:
        print("No snapshots found.")
        return 0
    print(f"{'RUN ID':<24} {'DATE':<12} {'TYPE':<10} {'STATUS':<10}")
    print("-" * 58)
    for rd in runs:
        run_date = "-"
        run_type = "-"
        status = "-"
        manifest_path = rd / "run_manifest.json"
        if manifest_path.is_file():
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
                run_date = m.get("run_date", "-")
                run_type = m.get("run_type", "-")
                status = m.get("status", "-")
            except (OSError, json.JSONDecodeError):
                logger.warning("Unable to read deformation run manifest: %s", manifest_path, exc_info=True)
        print(f"{rd.name:<24} {run_date:<12} {run_type:<10} {status:<10}")
    return 0


def _inspect_snapshot(snapshot_id: str, *, json_output: bool = False) -> int:
    run_dir = _resolve_snapshot(snapshot_id)
    if run_dir is None:
        print(f"deformation: snapshot not found: {snapshot_id}", file=sys.stderr)
        return 1

    manifest_path = run_dir / "run_manifest.json"
    manifest = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unable to read deformation run manifest: %s", manifest_path, exc_info=True)

    snapshot_path = _snapshot_json_path(run_dir)
    snapshot = {}
    if snapshot_path and snapshot_path.is_file():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Unable to read deformation snapshot: %s", snapshot_path, exc_info=True)

    if json_output:
        print(json.dumps({
            "status": "ok",
            "run_id": run_dir.name,
            "manifest": manifest,
            "snapshot_summary": _extract_summary(snapshot),
        }, indent=2, default=str))
        return 0

    print(f"Snapshot:   {run_dir.name}")
    print(f"Run Date:   {manifest.get('run_date', '-')}")
    print(f"Run Type:   {manifest.get('run_type', '-')}")
    print(f"Status:     {manifest.get('status', '-')}")
    print(f"Generated:  {manifest.get('generated_at', '-')}")
    print()

    # Proxy readings
    proxy = snapshot.get("proxy", {})
    if proxy:
        print("Proxy Readings:")
        print(f"  {'CHANNEL':<6} {'VALUE':>10} {'DIRECTION':<12} {'AVAILABLE':<10}")
        print(f"  {'-'*4}  {'-'*8}  {'-'*10}  {'-'*8}")
        for ch in ("M", "D", "K", "X"):
            val = proxy.get(ch)
            direction = (proxy.get("directions") or {}).get(ch, "-")
            available = (proxy.get("available") or {}).get(ch, False)
            val_str = f"{val:+.4f}" if isinstance(val, (int, float)) else "-"
            print(f"  {ch:<6} {val_str:>10} {direction:<12} {str(available):<10}")
    print()

    # State
    state = snapshot.get("state", {})
    if state:
        print("State:")
        print(f"  sigma_t:            {state.get('sigma_t', '-')}")
        print(f"  singular_flag:      {state.get('singular_flag', '-')}")
        print(f"  singular_time:      {state.get('structural_singular_time', '-')}")
        print(f"  leading_channel:    {state.get('leading_channel', '-')}")
        print(f"  pattern:            {state.get('pattern', '-')}")
    print()

    # Interpretation
    interp = snapshot.get("interpretation", {})
    if interp:
        print("Interpretation:")
        print(f"  severity:           {interp.get('severity', '-')}")
        print(f"  summary:            {interp.get('summary', '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


def _extract_summary(snapshot: dict) -> dict:
    proxy = snapshot.get("proxy", {})
    state = snapshot.get("state", {})
    interp = snapshot.get("interpretation", {})
    return {
        "run_date": snapshot.get("run_date"),
        "run_type": snapshot.get("run_type"),
        "escalation": snapshot.get("escalation"),
        "proxy": {ch: proxy.get(ch) for ch in ("M", "D", "K", "X")},
        "directions": proxy.get("directions", {}),
        "sigma_t": state.get("sigma_t"),
        "singular_flag": state.get("singular_flag"),
        "leading_channel": state.get("leading_channel"),
        "pattern": state.get("pattern"),
        "severity": interp.get("severity"),
        "summary": interp.get("summary"),
    }
