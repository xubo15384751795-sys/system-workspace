from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Any


ROOT = _workspace_root()
DATA_NLP = ROOT / "Data" / "nlp"


@dataclass(frozen=True)
class SourceManifest:
    document_id: str
    source_type: str
    source_path: str
    converted_by: str
    converted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    output_path: str = ""
    conversion_status: str = "success"
    known_issues: list[str] = field(default_factory=list)
    admission_status: str = "candidate"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        allowed_status = {"candidate", "reviewed", "admitted", "rejected"}
        if self.admission_status not in allowed_status:
            raise ValueError(f"admission_status must be one of {allowed_status}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "converted_by": self.converted_by,
            "converted_at": self.converted_at,
            "output_path": self.output_path,
            "conversion_status": self.conversion_status,
            "known_issues": list(self.known_issues),
            "admission_status": self.admission_status,
            "metadata": dict(self.metadata),
        }


def write_source_manifest(manifest: SourceManifest) -> Path:
    out_dir = DATA_NLP / "parsed_markdown"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{manifest.document_id}_manifest.json"
    out_path.write_text(
        json.dumps(manifest.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return out_path
