from __future__ import annotations

import re
from dataclasses import dataclass, field


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Section:
    section_id: str
    heading: str
    level: int
    text: str
    page_range: tuple[int, int] = (0, 0)


def parse_sections(text: str, document_id: str = "") -> list[Section]:
    if not text.strip():
        return []
    lines = text.splitlines()
    heading_positions: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        m = HEADING_PATTERN.match(line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            heading_positions.append((idx, level, heading))

    if not heading_positions:
        return [
            Section(
                section_id=f"{document_id}_sec_000",
                heading="",
                level=0,
                text=text.strip(),
            )
        ]

    sections: list[Section] = []
    for i, (line_idx, level, heading) in enumerate(heading_positions):
        start = line_idx + 1
        end = heading_positions[i + 1][0] if i + 1 < len(heading_positions) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        if body:
            sections.append(
                Section(
                    section_id=f"{document_id}_sec_{i:03d}",
                    heading=heading,
                    level=level,
                    text=body,
                )
            )
    return sections
