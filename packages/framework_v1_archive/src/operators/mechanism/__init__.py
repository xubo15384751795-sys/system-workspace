"""Detectors for named structural operators.

Each detector reads the canonical harvester panel (long-format:
``date | series_id | value``) and emits an ``ActivationRecord``.  The registry
entry in :mod:`src.operators.operator_registry` is the *identity* of the
operator; the detector is *how we decide it's on*.

Detectors here are intentionally small and pure:

- input is a DataFrame plus an as-of date,
- output is a dataclass with the same shape for every operator,
- no I/O, no side effects, no reaching into ``Output/`` — that's the caller's
  job.

This keeps the mechanism layer testable without dragging the whole daily
pipeline in.
"""

from __future__ import annotations

__all__ = ["ActivationRecord", "FundingPathStressDetector"]

from .funding_path_stress import ActivationRecord, FundingPathStressDetector
