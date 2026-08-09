#!/usr/bin/env python3
"""Peer entrypoint for Learning Hub runtime append.

Modules must not open ``Output/system_learning/runtime/`` directly. Use this
script or ``python3 -m system_learning record``.

Usage:
    python3 scripts/record_runtime_event.py \\
      --subsystem workbench --event-type note --severity info \\
      --payload-json '{"message": "operator note"}'
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HUB_SRC = _ROOT / "packages" / "learning_hub" / "src"
for _p in (str(_ROOT), str(_HUB_SRC), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main(argv: list[str] | None = None) -> int:
    from system_learning.cli import main as hub_main

    args = list(argv if argv is not None else sys.argv[1:])
    if "--system-root" not in args:
        args = ["--system-root", str(_ROOT), *args]
    return hub_main(["record", *args])


if __name__ == "__main__":
    raise SystemExit(main())
