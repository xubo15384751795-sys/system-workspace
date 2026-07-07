from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class PipelineStage(StrEnum):
    EVIDENCE_ACQUISITION = "evidence_acquisition"
    PROXY_CONSTRUCTION = "proxy_construction"
    PAPER_DIAGNOSTICS = "paper_diagnostics"
    ENGINEERING_AUDIT = "engineering_audit"
    EXPLORATORY_EXTENSIONS = "exploratory_extensions"
    SNAPSHOT_ASSEMBLY = "snapshot_assembly"


@dataclass(frozen=True)
class PipelineRunPolicy:
    run_extensions: bool = False
    run_belief_extension: bool = False
    run_ml_extensions: bool = False
    run_narrative_extension: bool = False
    persist_extension_outputs: bool = False

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "PipelineRunPolicy":
        cfg = config.get("pipeline", {})
        if not isinstance(cfg, dict):
            cfg = {}
        run_extensions = _as_bool(cfg.get("run_extensions"), default=False)
        return cls(
            run_extensions=run_extensions,
            run_belief_extension=run_extensions and _as_bool(cfg.get("run_belief_extension"), default=False),
            run_ml_extensions=run_extensions and _as_bool(cfg.get("run_ml_extensions"), default=False),
            run_narrative_extension=run_extensions and _as_bool(cfg.get("run_narrative_extension"), default=False),
            persist_extension_outputs=run_extensions and _as_bool(cfg.get("persist_extension_outputs"), default=False),
        )

    def stage_manifest(self) -> dict[str, Any]:
        return {
            "run_extensions": self.run_extensions,
            "run_belief_extension": self.run_belief_extension,
            "run_ml_extensions": self.run_ml_extensions,
            "run_narrative_extension": self.run_narrative_extension,
            "persist_extension_outputs": self.persist_extension_outputs,
        }


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)
