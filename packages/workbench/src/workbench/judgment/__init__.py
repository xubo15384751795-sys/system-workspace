"""Workbench Judgment Layer — bounded research judgment."""
from workbench.judgment.layer import build_judgment, write_outputs
from workbench.judgment.promotion_gate import run_promotion_gate
from workbench.judgment.synthesizer import ClaimEnvelope, JudgmentRecord, JudgmentSynthesizer

__all__ = [
    "build_judgment",
    "write_outputs",
    "run_promotion_gate",
    "ClaimEnvelope",
    "JudgmentRecord",
    "JudgmentSynthesizer",
]
