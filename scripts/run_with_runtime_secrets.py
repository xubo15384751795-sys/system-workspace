#!/usr/bin/env python3
"""Load mode-600 runtime sink credentials, then replace the process."""
from __future__ import annotations

import os
import sys

from system_runtime.runtime_secrets import load_runtime_secrets


def main(argv: list[str] | None = None) -> int:
    command = list(argv if argv is not None else sys.argv[1:])
    if not command:
        print("usage: run_with_runtime_secrets.py COMMAND [ARG ...]", file=sys.stderr)
        return 2
    load_runtime_secrets()
    os.execvpe(command[0], command, os.environ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
