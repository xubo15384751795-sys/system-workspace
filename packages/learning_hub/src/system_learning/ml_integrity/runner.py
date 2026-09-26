from __future__ import annotations

import argparse
import json
from pathlib import Path

from system_learning.ml_integrity import run_pollution_check
from system_learning.runtime.paths import HubPaths, default_system_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ML integrity pollution check (standalone sensor).")
    parser.add_argument("--system-root", type=Path, default=None)
    parser.add_argument("--signals-root", type=Path, default=None)
    parser.add_argument("--runs-root", type=Path, default=None)
    parser.add_argument("--events-dir", type=Path, default=None)
    parser.add_argument("--raise-on-red", action="store_true")
    args = parser.parse_args(argv)

    paths = HubPaths.resolve(args.system_root or default_system_root())
    report = run_pollution_check(
        signals_root=args.signals_root or paths.system_root / "Output" / "state" / "ml_signals",
        runs_root=args.runs_root or paths.system_root / "Output" / "deformation_runs",
        events_dir=args.events_dir or paths.events_dir,
        raise_on_red=args.raise_on_red,
    )
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
