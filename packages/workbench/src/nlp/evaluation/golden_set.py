from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root

from pydantic import BaseModel, Field

ROOT = _workspace_root()
DEFAULT_EVAL_DIR = ROOT / "Data" / "nlp" / "eval_sets"


class GoldenEventCard(BaseModel):
    golden_id: str
    source_text_quote: str
    expected_event_name: str = ""
    expected_entities: list[dict] = Field(default_factory=list)
    expected_variables: dict[str, list[str]] = Field(default_factory=dict)
    expected_triggers: list[str] = Field(default_factory=list)
    expected_anchors: list[str] = Field(default_factory=list)
    expected_liquidity_paths: list[str] = Field(default_factory=list)
    expected_visibility_shift: str = ""
    expected_policy_response: list[str] = Field(default_factory=list)
    required_quotes: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )


class GoldenQuery(BaseModel):
    query_id: str
    query_text: str
    expected_chunk_ids: list[str] = Field(default_factory=list)
    minimum_relevant_chunks: int = 0
    notes: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )


class GoldenVariableMapping(BaseModel):
    mapping_id: str
    source_text: str
    expected_variable_mapping: dict[str, list[str]] = Field(default_factory=dict)
    min_confidence_threshold: float = 0.3
    notes: str = ""
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )


def write_golden_event_cards(
    cards: list[GoldenEventCard],
    *,
    eval_dir: Path | None = None,
) -> Path:
    target = (eval_dir or DEFAULT_EVAL_DIR) / "golden_event_cards.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        for card in cards:
            f.write(card.model_dump_json(exclude_none=True) + "\n")
    return target


def read_golden_event_cards(
    *,
    eval_dir: Path | None = None,
) -> list[GoldenEventCard]:
    target = (eval_dir or DEFAULT_EVAL_DIR) / "golden_event_cards.jsonl"
    if not target.exists():
        return []
    cards: list[GoldenEventCard] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                cards.append(GoldenEventCard(**json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
    return cards


def write_golden_queries(
    queries: list[GoldenQuery],
    *,
    eval_dir: Path | None = None,
) -> Path:
    target = (eval_dir or DEFAULT_EVAL_DIR) / "golden_queries.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        for q in queries:
            f.write(q.model_dump_json(exclude_none=True) + "\n")
    return target


def read_golden_queries(
    *,
    eval_dir: Path | None = None,
) -> list[GoldenQuery]:
    target = (eval_dir or DEFAULT_EVAL_DIR) / "golden_queries.jsonl"
    if not target.exists():
        return []
    queries: list[GoldenQuery] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                queries.append(GoldenQuery(**json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
    return queries


def write_golden_variable_mappings(
    mappings: list[GoldenVariableMapping],
    *,
    eval_dir: Path | None = None,
) -> Path:
    target = (eval_dir or DEFAULT_EVAL_DIR) / "golden_variable_mappings.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        for m in mappings:
            f.write(m.model_dump_json(exclude_none=True) + "\n")
    return target


def read_golden_variable_mappings(
    *,
    eval_dir: Path | None = None,
) -> list[GoldenVariableMapping]:
    target = (eval_dir or DEFAULT_EVAL_DIR) / "golden_variable_mappings.jsonl"
    if not target.exists():
        return []
    mappings: list[GoldenVariableMapping] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                mappings.append(GoldenVariableMapping(**json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
    return mappings


def clear_golden_set(*, eval_dir: Path | None = None) -> dict[str, int]:
    base = eval_dir or DEFAULT_EVAL_DIR
    counts: dict[str, int] = {}
    for name in ["golden_event_cards.jsonl", "golden_queries.jsonl", "golden_variable_mappings.jsonl"]:
        path = base / name
        if path.exists():
            counts[name] = sum(1 for _ in path.read_text(encoding="utf-8").splitlines() if _.strip())
            path.unlink()
    return counts
