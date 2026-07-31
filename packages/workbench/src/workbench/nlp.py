from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workbench.context_budget import load_context_budget
from workbench.paths import workspace_root as _workspace_root
from workbench.prompt_assembly import assemble_full_prompt, build_prompt_sections


ROOT = _workspace_root()
CURRENT = ROOT / "Output" / "current"
OUTPUT = ROOT / "Output"
NLP_OUT = ROOT / "Output" / "workbench" / "nlp"


@dataclass(frozen=True)
class EvidenceChunk:
    evidence_id: str
    path: Path
    title: str
    text: str
    release_id: str = ""


def answer_question(
    question: str,
    *,
    top_k: int | None = None,
    include_prompt_sections: bool = False,
) -> dict[str, Any]:
    budget = load_context_budget()
    tk = budget.clamp_top_k(top_k if top_k is not None else budget.top_k_default)
    chunks = collect_current_chunks(chunk_window_chars=budget.chunk_window_chars)
    ranked = rank_chunks(question, chunks)[:tk]
    if not ranked:
        answer = "I could not find matching admitted/local evidence for that question."
        citations: list[dict[str, str]] = []
    else:
        answer = _compose_answer(question, ranked, excerpt_limit=budget.excerpt_chars)
        citations = [_citation(chunk, excerpt_limit=budget.excerpt_chars) for chunk in ranked]
    payload: dict[str, Any] = {
        "schema_version": "workbench.nlp_answer.v1",
        "question": question,
        "answer": answer,
        "citations": citations,
        "limits": [
            "Answered only from local Workbench current outputs and admitted evidence links.",
            "No external provider acquisition or live web lookup was performed.",
            "This extractive first pass is not a substitute for framework diagnosis.",
        ],
        "context_budget": {
            "chunk_window_chars": budget.chunk_window_chars,
            "excerpt_chars": budget.excerpt_chars,
            "top_k": tk,
            "top_k_max": budget.top_k_max,
        },
    }
    if include_prompt_sections:
        sections = build_prompt_sections(
            question,
            ranked,
            max_chunks=tk,
            excerpt_chars=budget.excerpt_chars,
        )
        payload["prompt_sections"] = sections
        payload["assembled_prompt"] = assemble_full_prompt(sections)
    return payload


def collect_current_chunks(*, chunk_window_chars: int | None = None) -> list[EvidenceChunk]:
    cw = chunk_window_chars if chunk_window_chars is not None else load_context_budget().chunk_window_chars
    release_id = _release_id()
    paths = [
        CURRENT / "00_READ_ME_FIRST.md",
        CURRENT / "latest_summary.md",
        CURRENT / "benchmark_evidence_dashboard.md",
        CURRENT / "NEXT_ACTIONS.md",
        OUTPUT / "system_learning" / "latest" / "system_health_report.md",
        CURRENT / "framework_output.json",
        CURRENT / "model_run.json",
        CURRENT / "run_manifest.json",
        CURRENT / "latest_dashboard.json",
    ]
    chunks: list[EvidenceChunk] = []
    for path in paths:
        if not path.exists():
            continue
        chunks.extend(
            _chunks_for_path(path.resolve(), release_id=release_id, max_chars=cw)
        )
    catalog = _catalog_path()
    if catalog and catalog.exists():
        chunks.extend(
            _chunks_for_path(catalog.resolve(), release_id=release_id, max_chars=cw)
        )
    return chunks


def rank_chunks(question: str, chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
    terms = _terms(question)
    scored: list[tuple[int, int, EvidenceChunk]] = []
    for idx, chunk in enumerate(chunks):
        haystack = " ".join([chunk.title, chunk.text]).lower()
        score = sum(3 if term in chunk.title.lower() else haystack.count(term) for term in terms)
        if chunk.path.name == "00_READ_ME_FIRST.md":
            score += 5
        if chunk.title.lower() in {"basic check", "evidence snapshot", "framework diagnosis"}:
            score += 3
        if chunk.path.suffix.lower() == ".json":
            score -= 1
        if score:
            scored.append((score, -idx, chunk))
    if not scored and chunks:
        scored = [(1, -idx, chunk) for idx, chunk in enumerate(chunks[:3])]
    return [chunk for _score, _idx, chunk in sorted(scored, reverse=True)]


def write_answer(payload: dict[str, Any]) -> None:
    NLP_OUT.mkdir(parents=True, exist_ok=True)
    (NLP_OUT / "last_answer.json").write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    lines = ["# Workbench NLP Answer", "", payload["answer"], "", "## Citations"]
    for idx, citation in enumerate(payload["citations"], start=1):
        lines.append(f"{idx}. `{citation['path']}` - {citation['excerpt']}")
    lines.extend(["", "## Limits", *[f"- {item}" for item in payload["limits"]], ""])
    if payload.get("context_budget"):
        lines.extend(["", "## Context budget", "```json", json.dumps(payload["context_budget"], indent=2), "```", ""])
    assembled = payload.get("assembled_prompt")
    if assembled:
        lines.extend(["## Assembled prompt (optional LLM handoff)", "", "```text", assembled, "```", ""])
        (NLP_OUT / "last_assembled_prompt.txt").write_text(assembled + "\n", encoding="utf-8")
    (NLP_OUT / "last_answer.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask a grounded question over Workbench current evidence.")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--top-k", type=int, default=None, help="Override top-k (clamped by context_budget).")
    parser.add_argument(
        "--with-prompt-bundle",
        action="store_true",
        help="Include modular prompt_sections + assembled_prompt in JSON (for LLM handoff).",
    )
    args = parser.parse_args(argv)
    payload = answer_question(
        " ".join(args.question),
        top_k=args.top_k,
        include_prompt_sections=args.with_prompt_bundle,
    )
    write_answer(payload)
    print(payload["answer"])
    if payload["citations"]:
        print()
        print("Citations:")
        for idx, citation in enumerate(payload["citations"], start=1):
            print(f"{idx}. {citation['path']}")
    print()
    print("Saved:")
    print("  Output/workbench/nlp/last_answer.md")
    print("  Output/workbench/nlp/last_answer.json")
    if args.with_prompt_bundle:
        print("  Output/workbench/nlp/last_assembled_prompt.txt")
    return 0


def _chunks_for_path(path: Path, *, release_id: str, max_chars: int) -> list[EvidenceChunk]:
    text = _read_text(path)
    if not text.strip():
        return []
    parts = _split_sections(text, max_chars=max_chars)
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    return [
        EvidenceChunk(
            evidence_id=f"{rel}#{idx}",
            path=path,
            title=title or path.name,
            text=body,
            release_id=release_id,
        )
        for idx, (title, body) in enumerate(parts, start=1)
        if body.strip()
    ]


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".json":
        try:
            return json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2, sort_keys=True)
        except Exception:
            return path.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def _split_sections(text: str, *, max_chars: int) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_title = ""
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            if current:
                sections.extend(_window(current_title, "\n".join(current), max_chars=max_chars))
            current_title = line.strip("# ").strip()
            current = [line]
        else:
            current.append(line)
    if current:
        sections.extend(_window(current_title, "\n".join(current), max_chars=max_chars))
    return sections


def _window(title: str, body: str, *, max_chars: int) -> list[tuple[str, str]]:
    body = body.strip()
    if len(body) <= max_chars:
        return [(title, body)]
    return [(title, body[start : start + max_chars]) for start in range(0, len(body), max_chars)]


def _terms(question: str) -> list[str]:
    aliases = {
        "watch": ["watch", "overall", "pressure", "inspect"],
        "risk": ["risk", "stress", "pressure", "overall"],
        "liquidity": ["liquidity", "funding", "treasury"],
        "sigma": ["sigma", "morphology", "leading", "singular"],
        "evidence": ["evidence", "release", "catalog", "provenance"],
        "财报": ["filing", "report", "document", "evidence"],
    }
    raw = re.findall(r"[\w\u4e00-\u9fff]+", question.lower())
    expanded = list(raw)
    for term in raw:
        expanded.extend(aliases.get(term, []))
    return [term for term in dict.fromkeys(expanded) if len(term) > 1]


def _compose_answer(
    question: str, chunks: list[EvidenceChunk], *, excerpt_limit: int
) -> str:
    lines = [f"Grounded answer for: {question}", ""]
    for chunk in chunks[:3]:
        excerpt = _excerpt(chunk.text, limit=excerpt_limit)
        lines.append(f"- {excerpt}")
    return "\n".join(lines)


def _citation(chunk: EvidenceChunk, *, excerpt_limit: int) -> dict[str, str]:
    path = chunk.path.relative_to(ROOT).as_posix() if chunk.path.is_relative_to(ROOT) else chunk.path.as_posix()
    return {
        "evidence_id": chunk.evidence_id,
        "path": path,
        "title": chunk.title,
        "release_id": chunk.release_id,
        "excerpt": _excerpt(chunk.text, limit=excerpt_limit),
    }


def _excerpt(text: str, limit: int = 260) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[: limit - 3].rstrip() + "..."


def _release_id() -> str:
    manifest = CURRENT / "run_manifest.json"
    if not manifest.exists():
        return ""
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8")).get("harvester_release", ""))
    except Exception:
        return ""


def _catalog_path() -> Path | None:
    manifest = CURRENT / "run_manifest.json"
    if not manifest.exists():
        return None
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8")).get("harvester_catalog_path")
    except Exception:
        return None
    return ROOT / raw if raw else None


if __name__ == "__main__":
    raise SystemExit(main())
