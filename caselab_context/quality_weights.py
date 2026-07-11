"""Quality-aware scoring for Paper note retrieval."""
from __future__ import annotations

QUALITY_BOOST: dict[str, float] = {
    "core": 0.12,
    "core_candidate": 0.08,
    "useful": 0.04,
    "seed": -0.04,
}

UNKNOWN_QUALITY_PENALTY = -0.02

QUALITY_RANK: dict[str, int] = {
    "seed": 0,
    "useful": 1,
    "core_candidate": 2,
    "core": 3,
}


def quality_rank(quality: str | None) -> int:
    if not quality:
        return -1
    return QUALITY_RANK.get(str(quality).strip().lower(), -1)


def passes_min_quality(quality: str | None, min_quality: str | None) -> bool:
    if not min_quality:
        return True
    required = quality_rank(min_quality)
    if required < 0:
        return True
    return quality_rank(quality) >= required


def filter_by_min_quality(results: list[dict], min_quality: str | None) -> list[dict]:
    if not min_quality:
        return results
    return [item for item in results if passes_min_quality(item.get("quality"), min_quality)]


def quality_bonus(quality: str | None) -> float:
    if not quality:
        return UNKNOWN_QUALITY_PENALTY
    return QUALITY_BOOST.get(str(quality).strip().lower(), 0.0)


def apply_quality_to_results(results: list[dict]) -> list[dict]:
    for item in results:
        bonus = quality_bonus(item.get("quality"))
        item["score"] = round(float(item.get("score") or 0.0) + bonus, 4)
        if bonus != 0.0:
            item["quality_adjusted"] = True
    return sorted(results, key=lambda row: float(row.get("score") or 0.0), reverse=True)
