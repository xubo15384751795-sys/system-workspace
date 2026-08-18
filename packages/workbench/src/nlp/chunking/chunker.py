from __future__ import annotations

from workbench.paths import workspace_root as _workspace_root

from nlp.chunking.chunk_schema import TextChunk
from nlp.parsing.section_parser import Section, parse_sections
from nlp.parsing.table_parser import detect_tables
from nlp.parsing.text_cleaner import clean_text
from nlp.rule_fingerprint import text_sha256

ROOT = _workspace_root()
MAX_CHARS_PER_CHUNK = 1800
MAX_TOKENS_ESTIMATE = int(MAX_CHARS_PER_CHUNK * 0.4)


class Chunker:
    def __init__(self, max_chars: int = MAX_CHARS_PER_CHUNK) -> None:
        self.max_chars = max_chars

    def chunk(self, text: str, *, document_id: str) -> list[TextChunk]:
        cleaned = clean_text(text)
        sections = parse_sections(cleaned, document_id=document_id)
        tables = detect_tables(cleaned)
        table_texts = {t.raw_text for t in tables}

        chunks: list[TextChunk] = []
        chunk_idx = 0

        for section in sections:
            section_chunks = self._chunk_section(section, tables, table_texts, document_id, chunk_idx)
            chunks.extend(section_chunks)
            chunk_idx += len(section_chunks)

        return chunks

    def _chunk_section(
        self,
        section: Section,
        tables: list,
        table_texts: set[str],
        document_id: str,
        start_idx: int,
    ) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        idx = start_idx
        parent_chunk_id = f"{section.section_id}_parent"
        parent_context_hash = text_sha256(section.text)

        paragraphs = _split_paragraphs(section.text)

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if para in table_texts:
                chunks.append(
                    TextChunk(
                        chunk_id=f"{document_id}_chunk_{idx:04d}",
                        document_id=document_id,
                        section_id=section.section_id,
                        parent_chunk_id=parent_chunk_id,
                        parent_section_title=section.heading,
                        parent_context_hash=parent_context_hash,
                        text=para,
                        chunk_type="table",
                        tokens_estimate=max(1, len(para) // 3),
                        metadata={
                            "heading": section.heading,
                            "section_level": section.level,
                        },
                    )
                )
                idx += 1
                continue

            if len(para) <= self.max_chars:
                chunks.append(
                    TextChunk(
                        chunk_id=f"{document_id}_chunk_{idx:04d}",
                        document_id=document_id,
                        section_id=section.section_id,
                        parent_chunk_id=parent_chunk_id,
                        parent_section_title=section.heading,
                        parent_context_hash=parent_context_hash,
                        text=para,
                        chunk_type="paragraph",
                        tokens_estimate=max(1, len(para) // 3),
                        metadata={
                            "heading": section.heading,
                            "section_level": section.level,
                        },
                    )
                )
                idx += 1
            else:
                for window_idx, window_text in enumerate(_sliding_window(para, self.max_chars)):
                    chunks.append(
                        TextChunk(
                            chunk_id=f"{document_id}_chunk_{idx:04d}",
                            document_id=document_id,
                            section_id=section.section_id,
                            parent_chunk_id=parent_chunk_id,
                            parent_section_title=section.heading,
                            parent_context_hash=parent_context_hash,
                            text=window_text,
                            chunk_type="sliding_window",
                            tokens_estimate=max(1, len(window_text) // 3),
                            metadata={
                                "heading": section.heading,
                                "section_level": section.level,
                                "window_index": window_idx,
                            },
                        )
                    )
                    idx += 1

        return chunks


def chunk_document(text: str, *, document_id: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[TextChunk]:
    chunker = Chunker(max_chars=max_chars)
    return chunker.chunk(text, document_id=document_id)


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _sliding_window(text: str, window_size: int, overlap: int = 200) -> list[str]:
    if len(text) <= window_size:
        return [text]
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + window_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            windows.append(chunk)
        start += window_size - overlap
    return windows
