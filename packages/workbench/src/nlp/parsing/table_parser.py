from __future__ import annotations

import re
from dataclasses import dataclass


TABLE_MARKER = re.compile(r"^\|.+\|$")
TABLE_SEPARATOR = re.compile(r"^\|[\s\-:]+\|$")


@dataclass(frozen=True)
class DetectedTable:
    lines: list[str]
    start_line: int
    end_line: int
    raw_text: str = ""


def detect_tables(text: str) -> list[DetectedTable]:
    lines = text.splitlines()
    tables: list[DetectedTable] = []
    in_table = False
    table_start = 0
    table_lines: list[str] = []

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if TABLE_MARKER.match(stripped) or (in_table and stripped.startswith("|")):
            if not in_table:
                table_start = idx
                in_table = True
            table_lines.append(line)
        else:
            if in_table:
                tables.append(
                    DetectedTable(
                        lines=list(table_lines),
                        start_line=table_start,
                        end_line=idx - 1,
                        raw_text="\n".join(table_lines),
                    )
                )
                table_lines = []
                in_table = False

    if in_table:
        tables.append(
            DetectedTable(
                lines=list(table_lines),
                start_line=table_start,
                end_line=len(lines) - 1,
                raw_text="\n".join(table_lines),
            )
        )

    return tables
