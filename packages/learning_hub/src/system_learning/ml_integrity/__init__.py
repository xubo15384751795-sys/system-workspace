"""ML Integrity subsystem for the System Learning Hub.

Two components:
  constitution  — declarative red lines; no ML/DL/NLP signal may cross them.
  pollution_monitor — runtime detector for feedback loops and sycophancy.
"""
from __future__ import annotations

from .constitution import (
    CONSTITUTION,
    ConstitutionEvaluationError,
    ConstitutionViolation,
    enforce,
)
from .pollution_monitor import PollutionReport, run_pollution_check

__all__ = [
    "CONSTITUTION",
    "ConstitutionEvaluationError",
    "ConstitutionViolation",
    "enforce",
    "PollutionReport",
    "run_pollution_check",
]
