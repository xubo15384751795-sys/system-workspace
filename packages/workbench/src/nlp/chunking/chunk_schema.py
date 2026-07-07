from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class TextChunk(BaseModel):
    chunk_id: str
    document_id: str
    section_id: str = ""
    parent_chunk_id: str = ""
    parent_section_title: str = ""
    parent_context_hash: str = ""
    text: str
    chunk_type: str = "paragraph"
    page_range: tuple[int, int] = (0, 0)
    tokens_estimate: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("chunk_type")
    @classmethod
    def _valid_chunk_type(cls, v: str) -> str:
        allowed = {"section", "paragraph", "table", "sliding_window", "quote"}
        if v not in allowed:
            raise ValueError(f"chunk_type must be one of {allowed}, got {v!r}")
        return v

    @field_validator("text")
    @classmethod
    def _non_empty_text(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("chunk text must not be empty")
        return v


class ChunkManifest(BaseModel):
    manifest_id: str
    document_id: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    chunks: list[TextChunk] = Field(default_factory=list)
    chunk_count: int = 0
    total_tokens_estimate: int = 0

    def model_post_init(self, _ctx: Any) -> None:
        self.chunk_count = len(self.chunks)
        self.total_tokens_estimate = sum(c.tokens_estimate for c in self.chunks)
