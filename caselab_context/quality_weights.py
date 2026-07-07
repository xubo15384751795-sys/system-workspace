"""Quality-aware scoring for Paper note retrieval."""
from __future__ import annotations

QUALITY_BOOST: dict[str, float] = {
    "core": 0.12,
    "core_candidate": 0.08,
    "useful": 0.04,
    "seed": -0.04,
}

UNKNOWN_QUALITY_PENALTY = -0.02


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
