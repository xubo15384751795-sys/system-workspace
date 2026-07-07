from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from workbench.paths import workspace_root as _workspace_root
from typing import Optional

from nlp.chunking.chunk_schema import TextChunk
from nlp.narrative.topic_model import TopicModel, TopicResult

ROOT = _workspace_root()


@dataclass
class NarrativeDriftReport:
    baseline_topics: list[TopicResult] = field(default_factory=list)
    current_topics: list[TopicResult] = field(default_factory=list)
    new_topics: list[TopicResult] = field(default_factory=list)
    faded_topics: list[TopicResult] = field(default_factory=list)
    merged_topics: list[dict] = field(default_factory=list)
    drift_signals: list[str] = field(default_factory=list)
    cross_domain_expansion: bool = False
    summary: str = ""


class NarrativeDriftDetector:
    """Detects narrative evolution between two sets of documents.

    Compares topic models from baseline (earlier documents) and current
    (later documents) to identify:
    - New topics that emerged
    - Topics that faded
    - Topics that merged or split
    - Cross-domain narrative expansion signals
    """

    def __init__(
        self,
        *,
        min_topic_size: int = 3,
        keyword_overlap_threshold: float = 0.25,
        cross_domain_keywords: list[str] | None = None,
    ) -> None:
        self.min_topic_size = min_topic_size
        self.overlap_threshold = keyword_overlap_threshold
        self.cross_domain_keywords = cross_domain_keywords or [
            "financing", "credit", "funding", "liquidity",
            "energy", "infrastructure", "technology", "ai",
            "regulation", "policy", "sovereign", "geopolitical",
        ]

    def detect(
        self,
        baseline_chunks: list[TextChunk],
        current_chunks: list[TextChunk],
        *,
        baseline_label: str = "baseline",
        current_label: str = "current",
    ) -> NarrativeDriftReport:
        model = TopicModel(min_topic_size=self.min_topic_size)
        baseline_topics = model.fit(baseline_chunks) if baseline_chunks else []
        current_topics = model.fit(current_chunks) if current_chunks else []

        if not baseline_topics:
            return NarrativeDriftReport(
                baseline_topics=[],
                current_topics=current_topics,
                new_topics=current_topics,
                drift_signals=["No baseline topics — all current topics are treated as new."],
                summary=f"No baseline to compare against. {len(current_topics)} topics in {current_label}.",
            )

        baseline_kw_sets = {t.topic_id: set(t.keywords) for t in baseline_topics}
        current_kw_sets = {t.topic_id: set(t.keywords) for t in current_topics}

        new_topics: list[TopicResult] = []
        faded_topics: list[TopicResult] = []
        merged: list[dict] = []

        for ct in current_topics:
            ct_kw = current_kw_sets.get(ct.topic_id, set())
            matched = False
            for bt in baseline_topics:
                bt_kw = baseline_kw_sets.get(bt.topic_id, set())
                if not bt_kw or not ct_kw:
                    continue
                overlap = len(ct_kw & bt_kw) / max(1, min(len(ct_kw), len(bt_kw)))
                if overlap >= self.overlap_threshold:
                    matched = True
                    if overlap < 0.6:
                        merged.append({
                            "baseline_topic": bt.label,
                            "current_topic": ct.label,
                            "keyword_overlap": round(overlap, 3),
                            "shared_keywords": sorted(ct_kw & bt_kw),
                        })
                    break
            if not matched:
                new_topics.append(ct)

        for bt in baseline_topics:
            bt_kw = baseline_kw_sets.get(bt.topic_id, set())
            matched = False
            for ct in current_topics:
                ct_kw = current_kw_sets.get(ct.topic_id, set())
                if not bt_kw or not ct_kw:
                    continue
                overlap = len(ct_kw & bt_kw) / max(1, min(len(ct_kw), len(bt_kw)))
                if overlap >= self.overlap_threshold:
                    matched = True
                    break
            if not matched:
                faded_topics.append(bt)

        drift_signals = _compute_drift_signals(
            baseline_topics=baseline_topics,
            current_topics=current_topics,
            new_topics=new_topics,
            faded_topics=faded_topics,
            merged_topics=merged,
            cross_domain_keywords=self.cross_domain_keywords,
        )

        cross_domain = any("cross-domain" in s.lower() for s in drift_signals)

        return NarrativeDriftReport(
            baseline_topics=baseline_topics,
            current_topics=current_topics,
            new_topics=new_topics,
            faded_topics=faded_topics,
            merged_topics=merged,
            drift_signals=drift_signals,
            cross_domain_expansion=cross_domain,
            summary=(
                f"{len(new_topics)} new, {len(faded_topics)} faded, "
                f"{len(merged)} merged topics. "
                f"Drift signals: {'; '.join(drift_signals) if drift_signals else 'none'}"
            ),
        )


def detect_narrative_drift(
    baseline_chunks: list[TextChunk],
    current_chunks: list[TextChunk],
    *,
    min_topic_size: int = 3,
) -> NarrativeDriftReport:
    detector = NarrativeDriftDetector(min_topic_size=min_topic_size)
    return detector.detect(baseline_chunks, current_chunks)


def _compute_drift_signals(
    *,
    baseline_topics: list[TopicResult],
    current_topics: list[TopicResult],
    new_topics: list[TopicResult],
    faded_topics: list[TopicResult],
    merged_topics: list[dict],
    cross_domain_keywords: list[str],
) -> list[str]:
    signals: list[str] = []

    if new_topics:
        labels = [t.label for t in new_topics]
        signals.append(f"New topic(s) emerged: {', '.join(labels[:3])}")

    if faded_topics:
        labels = [t.label for t in faded_topics]
        signals.append(f"Topic(s) faded: {', '.join(labels[:3])}")

    if merged_topics:
        signals.append(f"{len(merged_topics)} topic(s) show partial merging/splitting")

    current_count = len(current_topics)
    baseline_count = len(baseline_topics)
    if baseline_count > 0:
        ratio = current_count / baseline_count
        if ratio >= 1.8:
            signals.append(f"Topic fragmentation: {baseline_count} → {current_count}")
        elif ratio <= 0.6:
            signals.append(f"Topic consolidation: {baseline_count} → {current_count}")

    all_current_kw: set[str] = set()
    for t in current_topics:
        all_current_kw.update(t.keywords)
    all_baseline_kw: set[str] = set()
    for t in baseline_topics:
        all_baseline_kw.update(t.keywords)

    cross_kw = set(cross_domain_keywords)
    current_cross = all_current_kw & cross_kw
    baseline_cross = all_baseline_kw & cross_kw
    if current_cross and not baseline_cross:
        signals.append("Cross-domain expansion: keywords from new domains appear")
    elif current_cross and baseline_cross and len(current_cross) > len(baseline_cross):
        new_domains = current_cross - baseline_cross
        if new_domains:
            signals.append(f"Cross-domain linkage expanding: {sorted(new_domains)[:4]}")

    return signals
