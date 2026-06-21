#!/usr/bin/env python3
"""Thin wrapper for Workbench NLP evidence query.

This script delegates to Workbench/src/workbench/nlp.py.
Used by: ./sys ask "question"

The canonical implementation lives in Workbench; this wrapper exists only
so that root-level entry points (sys, Justfile, tests) continue to work.
"""
from __future__ import annotations

from pathlib import Path

from _workspace_imports import add_workbench_src
add_workbench_src()

from workbench.nlp import main

if __name__ == "__main__":
    raise SystemExit(main())
