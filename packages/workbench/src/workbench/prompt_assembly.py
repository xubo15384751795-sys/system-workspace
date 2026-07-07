"""Modular system prompt assembly for agents (constitution + task + evidence).

Mirrors the Claude Code pattern of static prefix vs session-specific suffix:
assemble_full_prompt() inserts PROMPT_DYNAMIC_BOUNDARY between stable sections and
the evidence digest so callers can treat caching / budgeting explicitly.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from workbench.paths import workspace_root

PROMPT_DYNAMIC_BOUNDARY = "PROMPT_DYNAMIC_BOUNDARY"


class _ChunkLike(Protocol):
    title: str
    path: Path
    text: str


def _excerpt(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[: limit - 3].rstrip() + "..."


def _sections_dir(root: Path | None = None) -> Path:
    base = root or workspace_root()
    return base / "Workbench" / "contracts" / "workbench" / "agent_prompt_sections"


def load_static_section(filename: str, *, root: Path | None = None) -> str:
    path = _sections_dir(root) / filename
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def format_task_shell(question: str, *, root: Path | None = None) -> str:
    raw = load_static_section("task_shell.md", root=root)
    if not raw:
        return f"User question:\n\n{question}\n"
    return raw.format(question=question)


def format_evidence_digest(
    chunks: list[_ChunkLike],
    *,
    max_chunks: int,
    excerpt_chars: int,
) -> str:
    lines: list[str] = ["## Evidence digest (dynamic)", ""]
    for ch in chunks[:max_chunks]:
        rel = ch.path
        try:
            rel_s = rel.relative_to(workspace_root()).as_posix()
        except ValueError:
            rel_s = rel.as_posix()
        ex = _excerpt(ch.text, excerpt_chars)
        lines.append(f"- **{ch.title}** (`{rel_s}`)\n  {ex}\n")
    return "\n".join(lines).strip()


def build_prompt_sections(
    question: str,
    ranked_chunks: list[_ChunkLike],
    *,
    max_chunks: int,
    excerpt_chars: int,
    root: Path | None = None,
) -> dict[str, str]:
    constitution = load_static_section("constitution.md", root=root)
    grounding = load_static_section("evidence_grounding.md", root=root)
    task = format_task_shell(question, root=root)
    digest = format_evidence_digest(
        ranked_chunks, max_chunks=max_chunks, excerpt_chars=excerpt_chars
    )
    return {
        "constitution": constitution,
        "evidence_grounding": grounding,
        "task": task,
        "evidence_digest": digest,
    }


def assemble_full_prompt(sections: dict[str, str]) -> str:
    static = "\n\n".join(
        s for s in (sections.get("constitution"), sections.get("evidence_grounding"), sections.get("task")) if s
    )
    dynamic = sections.get("evidence_digest", "")
    if not static:
        return dynamic
    if not dynamic:
        return static
    return (
        f"{static}\n\n---\n{PROMPT_DYNAMIC_BOUNDARY}\n---\n\n{dynamic}"
    )
