from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from nlp.chunking.chunk_schema import TextChunk
from nlp.extraction.schemas import ExtractedEntity


class TableRowEntity(BaseModel):
    row_label: str = ""
    values: dict[str, str] = Field(default_factory=dict)
    entity_type_hint: str = ""
    variable_hint: list[str] = Field(default_factory=list)
    evidence_quote: str = ""


class ExtractedTable(BaseModel):
    table_id: str
    chunk_id: str
    document_id: str
    caption: str = ""
    headers: list[str] = Field(default_factory=list)
    rows: list[TableRowEntity] = Field(default_factory=list)
    raw_text: str = ""


def extract_from_table_chunks(
    chunks: list[TextChunk],
) -> list[ExtractedTable]:
    """Extract structured data from table-type chunks.

    Parses markdown table blocks into row entities with headers,
    and infers entity types and variable hints for each row.
    """
    tables: list[ExtractedTable] = []
    for chunk in chunks:
        if chunk.chunk_type != "table":
            continue
        et = _parse_table_chunk(chunk)
        if et and et.rows:
            tables.append(et)
    return tables


def table_rows_to_entities(
    tables: list[ExtractedTable],
) -> list[ExtractedEntity]:
    """Convert structured table rows into ExtractedEntity instances.

    Each row becomes an entity; the row label becomes the entity text,
    and column values become evidence quotes.
    """
    entities: list[ExtractedEntity] = []
    for table in tables:
        for row in table.rows:
            if not row.row_label.strip():
                continue
            quote = row.evidence_quote or row.row_label
            if row.values:
                value_text = "; ".join(f"{k}: {v}" for k, v in row.values.items() if v)
                quote = f"{row.row_label}: {value_text}" if value_text else quote
            entities.append(
                ExtractedEntity(
                    chunk_id=table.chunk_id,
                    text=row.row_label,
                    type=row.entity_type_hint or "asset",
                    variable_hint=list(row.variable_hint) or ["A"],
                    evidence_quote=quote,
                )
            )
    return entities


def extract_table_entities(
    chunks: list[TextChunk],
) -> list[ExtractedEntity]:
    """Convenience: extract table chunks and convert to entities in one call."""
    tables = extract_from_table_chunks(chunks)
    return table_rows_to_entities(tables)


def _parse_table_chunk(chunk: TextChunk) -> Optional[ExtractedTable]:
    text = chunk.text.strip()
    lines = [line.strip() for line in text.split("\n") if line.strip() and "|" in line]
    if len(lines) < 2:
        return None

    header_cells = [c.strip() for c in lines[0].split("|") if c.strip()]
    separator_idx = 1 if len(lines) > 1 and re.match(r"^[\|\s\-:]+$", lines[1]) else -1
    start_row = separator_idx + 1 if separator_idx >= 0 else 1

    headers = header_cells
    rows: list[TableRowEntity] = []
    for line in lines[start_row:]:
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if not cells:
            continue
        label = cells[0] if cells else ""
        values: dict[str, str] = {}
        for i, cell in enumerate(cells[1:], 1):
            if i < len(headers):
                values[headers[i]] = cell
        entity_hint, var_hint = _infer_table_entity_type(label, headers)
        rows.append(
            TableRowEntity(
                row_label=label,
                values=values,
                entity_type_hint=entity_hint,
                variable_hint=var_hint,
                evidence_quote=line,
            )
        )

    caption = chunk.metadata.get("heading", "") if chunk.metadata else ""
    return ExtractedTable(
        table_id=f"table_{chunk.chunk_id}",
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        caption=caption,
        headers=headers,
        rows=rows,
        raw_text=text,
    )


def _infer_table_entity_type(row_label: str, headers: list[str]) -> tuple[str, list[str]]:
    joined = f"{row_label} {' '.join(headers)}".lower()

    if any(kw in joined for kw in ("bond", "treasury", "security", "mbs", "cdo", "clo", "equity", "stock")):
        return ("asset", ["A", "L"])
    if any(kw in joined for kw in ("loan", "credit", "debt", "private credit", "lending")):
        return ("asset", ["A", "L", "tau"])
    if any(kw in joined for kw in ("deposit", "funding", "repo", "reserve")):
        return ("liability", ["A", "L", "tau"])
    if any(kw in joined for kw in ("capital", "buffer", "ratio", "LCR", "NSFR", "tier")):
        return ("policy_tool", ["P", "A"])
    if any(kw in joined for kw in ("spread", "yield", "rate", "basis", "OAS", "price", "premium")):
        return ("valuation_gap", ["A", "V", "tau"])
    if any(kw in joined for kw in ("loss", "write", "impairment", "default", "downgrade")):
        return ("risk_event", ["A", "L", "V"])
    if any(kw in joined for kw in ("bank", "fund", "institution", "issuer", "borrower")):
        return ("institution", ["S", "P"])

    return ("asset", ["A"])
