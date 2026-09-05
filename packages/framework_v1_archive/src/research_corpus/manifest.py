from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from src.research_corpus.taxonomy import (
    DEFAULT_NUMERIC_EVIDENCE_TYPE,
    DEFAULT_PROXY_CORE_PERMISSION,
    DocumentType,
    NumericEvidenceType,
    ProviderGroup,
    UsageTag,
)


@dataclass(frozen=True)
class CorpusDocumentSeed:
    provider: str
    title: str
    url: str
    document_type: DocumentType = DocumentType.OTHER
    publication_date: str | None = None
    topics: tuple[str, ...] = ()
    asset_class: tuple[str, ...] = ()
    strategy_family: tuple[str, ...] = ()
    usage_tags: tuple[UsageTag, ...] = ()


@dataclass(frozen=True)
class CorpusDocumentManifest:
    corpus_id: str
    provider: str
    title: str
    publication_date: str | None
    url: str
    local_path: str
    file_hash: str
    document_type: DocumentType
    topics: tuple[str, ...] = ()
    asset_class: tuple[str, ...] = ()
    strategy_family: tuple[str, ...] = ()
    usage_tags: tuple[UsageTag, ...] = ()
    provider_group: ProviderGroup | None = None
    allowed_for_proxy_core: bool = DEFAULT_PROXY_CORE_PERMISSION
    numeric_evidence_type: NumericEvidenceType = DEFAULT_NUMERIC_EVIDENCE_TYPE
    manual_approval: bool = False
    accessed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    notes: str = ""

    def __post_init__(self) -> None:
        if self.allowed_for_proxy_core and not self.manual_approval:
            raise ValueError("proxy-core corpus use requires manual_approval=True")
        if self.allowed_for_proxy_core and self.numeric_evidence_type != NumericEvidenceType.FORMAL_MARKET_DATA:
            raise ValueError("proxy-core corpus use requires formal_market_data evidence type")

    def to_dict(self) -> dict[str, Any]:
        provider_group = self.provider_group.value if self.provider_group else None
        return {
            "corpus_id": self.corpus_id,
            "provider": self.provider,
            "provider_group": provider_group,
            "title": self.title,
            "publication_date": self.publication_date,
            "url": self.url,
            "local_path": self.local_path,
            "file_hash": self.file_hash,
            "document_type": self.document_type.value,
            "topics": list(self.topics),
            "asset_class": list(self.asset_class),
            "strategy_family": list(self.strategy_family),
            "usage_tags": [tag.value for tag in self.usage_tags],
            "allowed_for_proxy_core": self.allowed_for_proxy_core,
            "numeric_evidence_type": self.numeric_evidence_type.value,
            "manual_approval": self.manual_approval,
            "accessed_at": self.accessed_at,
            "notes": self.notes,
        }

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    out = []
    for char in value.lower():
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "document"


__all__ = ["CorpusDocumentManifest", "CorpusDocumentSeed", "sha256_file", "slugify"]
