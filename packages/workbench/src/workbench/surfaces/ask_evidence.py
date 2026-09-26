#!/usr/bin/env python3
"""Thin CLI wrapper for workbench.nlp.answer_question.

Called by ``./sys ask "question"``.

Usage:
    python scripts/ask_evidence.py "what evidence supports the current check?"
"""
from __future__ import annotations

import sys

from workbench.nlp import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
