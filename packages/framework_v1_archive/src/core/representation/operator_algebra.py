from __future__ import annotations

from src.operators.operator_schema import OperatorSequence, OperatorStep, StructuralStateOperand


def compose(*steps: OperatorStep) -> OperatorSequence:
    """Compatibility wrapper for the old core.representation import path."""

    return OperatorSequence.from_steps(tuple(steps))


__all__ = ["OperatorSequence", "OperatorStep", "StructuralStateOperand", "compose"]
