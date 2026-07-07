"""Governance guard layer for the System Learning Hub.

Read-only audit that blocks reuse of contaminated, frozen, missing-artifact, or
diagnostic-only entities on the live daily surface. Registry-driven; never
mutates signals, configs, or registries.
"""
from __future__ import annotations

from .audit import (
    AuditReport,
    Finding,
    build_daily_corpus,
    run_governance_audit,
    write_report,
)
from .posture import (
    PostureEntry,
    ResearchPostureDigest,
    build_posture_digest,
    run_research_posture,
    write_posture,
)
from .registry import DEFAULT_REGISTRY_RELPATH, Entity, Posture, Registry, load_registry

__all__ = [
    "AuditReport",
    "Finding",
    "Entity",
    "Posture",
    "Registry",
    "PostureEntry",
    "ResearchPostureDigest",
    "DEFAULT_REGISTRY_RELPATH",
    "build_daily_corpus",
    "build_posture_digest",
    "load_registry",
    "run_governance_audit",
    "run_research_posture",
    "write_posture",
    "write_report",
]
