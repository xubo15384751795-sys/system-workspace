from __future__ import annotations

from typing import Any

from src.core.interfaces import (
    AnomalyDetectorInterface,
    NarrativeDetectorInterface,
    ReflexivityDetectorInterface,
    SnapshotStoreInterface,
)
from src.ml.ml_anomaly import IsolationForestDetector
from src.ml.ml_narrative import SentenceTransformerDetector
from src.ml.ml_reflexivity import DTWReflexivityDetector
from src.stubs.stubs import (
    StubAnomalyDetector,
    StubNarrativeDetector,
    StubReflexivityDetector,
)


def _detector_section(config: dict[str, Any], key: str) -> dict[str, Any]:
    raw = config.get("detectors")
    if not isinstance(raw, dict):
        return {}
    block = raw.get(key)
    return block if isinstance(block, dict) else {}


def build_anomaly_detector(config: dict[str, Any]) -> AnomalyDetectorInterface:
    cfg = _detector_section(config, "anomaly")
    backend = str(cfg.get("backend", "stub")).strip().lower()
    if backend == "isolation_forest":
        sub = cfg.get("isolation_forest")
        sub = sub if isinstance(sub, dict) else {}
        return IsolationForestDetector(
            contamination=float(sub.get("contamination", 0.05)),
            random_state=int(sub.get("random_state", 7)),
            min_samples=int(sub.get("min_samples", 10)),
        )
    if backend == "dl":
        from src.ml.dl_anomaly_detector import LSTMAutoencoderDetector

        release = str(cfg.get("model_release", "latest"))
        return LSTMAutoencoderDetector.load(release, config=config)
    return StubAnomalyDetector()


def build_narrative_detector(config: dict[str, Any]) -> NarrativeDetectorInterface:
    cfg = _detector_section(config, "narrative")
    backend = str(cfg.get("backend", "stub")).strip().lower()
    if backend in {"sentence_transformer", "keyword"}:
        return SentenceTransformerDetector()
    if backend in {"semantic_prototype", "dl", "embedding"}:
        from src.ml.dl_narrative_detector import PrototypeEmbeddingNarrativeDetector

        sub = cfg.get("semantic_prototype")
        sub = sub if isinstance(sub, dict) else {}
        return PrototypeEmbeddingNarrativeDetector(
            model_name=str(sub.get("model_name", "all-MiniLM-L6-v2")),
        )
    return StubNarrativeDetector()


def build_reflexivity_detector(config: dict[str, Any]) -> ReflexivityDetectorInterface:
    cfg = _detector_section(config, "reflexivity")
    backend = str(cfg.get("backend", "stub")).strip().lower()
    if backend == "dtw":
        sub = cfg.get("dtw")
        sub = sub if isinstance(sub, dict) else {}
        return DTWReflexivityDetector(channel_threshold=float(sub.get("channel_threshold", 0.6)))
    if backend == "dl":
        from src.ml.dl_reflexivity_detector import GraphReflexivityDetector

        sub = cfg.get("graph")
        sub = sub if isinstance(sub, dict) else {}
        return GraphReflexivityDetector(
            window=int(sub.get("window", 60)),
            channel_threshold=float(sub.get("channel_threshold", 0.6)),
        )
    return StubReflexivityDetector()


def maybe_fit_stateful_detectors(
    anomaly: AnomalyDetectorInterface,
    config: dict[str, Any],
    snapshot_store: SnapshotStoreInterface,
) -> None:
    """Fit detectors that expose ``fit_from_history`` (e.g. isolation forest, LSTM AE)."""
    cfg = _detector_section(config, "anomaly")
    backend = str(cfg.get("backend", "stub")).strip().lower()
    if backend == "isolation_forest":
        sub = cfg.get("isolation_forest")
        sub = sub if isinstance(sub, dict) else {}
    elif backend == "dl":
        sub = cfg.get("dl")
        sub = sub if isinstance(sub, dict) else {}
    else:
        return
    start = str(sub.get("fit_history_start", "1900-01-01"))
    end = str(sub.get("fit_history_end", "9999-12-31"))
    fitter = getattr(anomaly, "fit_from_history", None)
    if callable(fitter):
        fitter(snapshot_store, start, end)
    binder = getattr(anomaly, "bind_snapshot_store", None)
    if callable(binder):
        binder(snapshot_store)


def build_all_detectors(
    config: dict[str, Any],
    snapshot_store: SnapshotStoreInterface,
) -> tuple[AnomalyDetectorInterface, NarrativeDetectorInterface, ReflexivityDetectorInterface]:
    anomaly = build_anomaly_detector(config)
    maybe_fit_stateful_detectors(anomaly, config, snapshot_store)
    narrative = build_narrative_detector(config)
    reflexivity = build_reflexivity_detector(config)
    return anomaly, narrative, reflexivity
