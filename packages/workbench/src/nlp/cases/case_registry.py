from __future__ import annotations

import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

from pydantic import BaseModel, Field, field_validator

ROOT = _workspace_root()
DEFAULT_CASE_DIR = ROOT / "Data" / "nlp" / "case_library"
STRUCTURAL_VARIABLES = ("S", "A", "L", "V", "P", "tau")


class CaseProfile(BaseModel):
    case_id: str
    case_name: str
    vintage: str = ""
    variable_vector: dict[str, float] = Field(
        default_factory=lambda: {v: 0.0 for v in STRUCTURAL_VARIABLES}
    )
    tags: list[str] = Field(default_factory=list)
    narrative_summary: str = ""
    canonical_event_card_path: str = ""
    source_documents: list[str] = Field(default_factory=list)
    event_patterns: list[str] = Field(default_factory=list)
    artifact_class: str = "historical_case_profile"
    claim_ceiling: str = "historical_reference_only"
    promotion_allowed: bool = False

    @field_validator("artifact_class")
    @classmethod
    def _historical_artifact_only(cls, value: str) -> str:
        if value != "historical_case_profile":
            raise ValueError("case profiles must remain historical_case_profile artifacts")
        return value

    @field_validator("claim_ceiling")
    @classmethod
    def _historical_claim_ceiling(cls, value: str) -> str:
        if value != "historical_reference_only":
            raise ValueError("case profiles must remain historical_reference_only")
        return value

    @field_validator("promotion_allowed")
    @classmethod
    def _never_promotable(cls, value: bool) -> bool:
        if value:
            raise ValueError("historical case profiles cannot authorize promotion")
        return value


class CaseRegistry:
    """Registry of canonical structural case profiles.

    Each case is a historically significant event with a variable vector
    that captures its S-A-L-V-P-tau intensity profile. New events are
    compared against this library for structural similarity.
    """

    def __init__(self, case_dir: Path | None = None) -> None:
        self.case_dir = case_dir or DEFAULT_CASE_DIR
        self._cases: dict[str, CaseProfile] = {}

    def load(self) -> int:
        self._cases.clear()
        if not self.case_dir.exists():
            return 0
        for path in sorted(self.case_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                profile = CaseProfile(**data)
                self._cases[profile.case_id] = profile
            except (json.JSONDecodeError, ValueError):
                continue
        return len(self._cases)

    def add(self, profile: CaseProfile) -> None:
        self._cases[profile.case_id] = profile

    def save_case(self, profile: CaseProfile) -> Path:
        self.case_dir.mkdir(parents=True, exist_ok=True)
        path = self.case_dir / f"{profile.case_id}.json"
        path.write_text(
            profile.model_dump_json(indent=2, exclude_none=True) + "\n",
            encoding="utf-8",
        )
        self._cases[profile.case_id] = profile
        return path

    def get(self, case_id: str) -> Optional[CaseProfile]:
        return self._cases.get(case_id)

    def list_cases(self) -> list[CaseProfile]:
        return sorted(self._cases.values(), key=lambda c: c.case_id)

    @property
    def case_ids(self) -> list[str]:
        return sorted(self._cases.keys())

    @property
    def variable_matrix(self) -> dict[str, dict[str, float]]:
        return {cid: cp.variable_vector for cid, cp in self._cases.items()}

    @property
    def tag_index(self) -> dict[str, list[str]]:
        idx: dict[str, list[str]] = {}
        for case_id, profile in self._cases.items():
            for tag in profile.tags:
                idx.setdefault(tag, []).append(case_id)
        return idx

    def __len__(self) -> int:
        return len(self._cases)

    def __contains__(self, case_id: str) -> bool:
        return case_id in self._cases


def load_case_library(case_dir: Path | None = None) -> CaseRegistry:
    registry = CaseRegistry(case_dir=case_dir)
    registry.load()
    return registry
