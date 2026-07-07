"""Public CLI for Agent Routing shadow diagnostics."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HARNESS_ROOT = Path(__file__).resolve().parents[1]
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

from tools.task_router import route_task  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Route a task through the harness router.")
    parser.add_argument("task")
    parser.add_argument("--artifact", action="append", default=[])
    args = parser.parse_args(argv)

    decision = route_task(args.task, artifacts=args.artifact)
    print(json.dumps(decision, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
