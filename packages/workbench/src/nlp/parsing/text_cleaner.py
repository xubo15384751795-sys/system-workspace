from __future__ import annotations

import re


def clean_text(text: str, *, remove_headers_footers: bool = True) -> str:
    if remove_headers_footers:
        text = _strip_headers_footers(text)
    text = _normalize_whitespace(text)
    text = _remove_page_numbers(text)
    return text.strip()


REFERENCE_PATTERNS = re.compile(
    r"(?:\n|^)\s*(?:References?|Bibliography|Works Cited|"
    r"REFERENCES|BIBLIOGRAPHY)\s*\n",
    re.IGNORECASE,
)


def strip_references(text: str) -> str:
    m = REFERENCE_PATTERNS.search(text)
    if m:
        return text[: m.start()].rstrip()
    return text


def _strip_headers_footers(text: str) -> str:
    lines = text.splitlines()
    if len(lines) < 10:
        return text
    header = lines[0].strip()
    candidates = {header}
    if len(lines) > 1:
        candidates.add(lines[1].strip())
    footer_candidates = {lines[-1].strip(), lines[-2].strip()}
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in candidates and stripped:
            continue
        if stripped in footer_candidates and stripped and len(stripped) < 120:
            continue
        kept.append(line)
    return "\n".join(kept)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r" {2,}\n", "\n", text)
    return text


def _remove_page_numbers(text: str) -> str:
    return re.sub(r"\n\s*\d{1,4}\s*\n", "\n", text)
