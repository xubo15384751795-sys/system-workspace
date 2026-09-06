"""Workbench Judgment Layer — bounded research judgment."""
from workbench.judgment.layer import build_judgment, write_outputs
from workbench.judgment.neutral_state import compare_readings, reading_from_snapshot
from workbench.judgment.promotion_gate import run_promotion_gate
from workbench.judgment.synthesizer import ClaimEnvelope, JudgmentRecord, JudgmentSynthesizer

__all__ = [
    "build_judgment",
    "write_outputs",
    "compare_readings",
    "reading_from_snapshot",
    "run_promotion_gate",
    "ClaimEnvelope",
    "JudgmentRecord",
    "JudgmentSynthesizer",
]
