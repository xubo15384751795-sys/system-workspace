"""Runtime assembly — RuntimeWarning for legacy backend path."""
from __future__ import annotations

from system_runtime.paths import WorkspacePaths

import json
import warnings
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.core.calibration import build_proxy_weights, build_thresholds
from src.core.execution import RunContext
from src.core.models import Snapshot
from src.core.pipeline import ResearchPipeline
from src.core.runtime_context import RuntimePaths
from src.data.gateway import DataHubBridge, create_data_hub
from src.data.paths import resolve_data_root, resolve_snapshot_store_path
from src.data.snapshot_store import DuckDBSnapshotStore
from src.data_access.freeze import check_legacy_allowed
from src.derivation.belief_builder import DefaultBeliefBuilder
from src.derivation.proxy_builder import DefaultProxyBuilder
from src.derivation.singular_detector import ThresholdSingularDetector
from src.dynamics.ode_engine import ScipyODEEngine
from src.mechanisms.default_mechanisms import build_default_mechanism_registry
from src.ml.detector_factory import build_all_detectors
from src.framework_nlp.event_translator import NLPEventTranslator
from src.operators.operator_registry import build_default_operator_registry
from src.output.output_exporter import export_snapshot_artifacts
from src.runtime.evidence_store import RuntimeEvidenceStore
from src.runtime.system_api import StructuralSystemAPI
from src.signals import CrossValidator, FastSignalComputer, FastSignalConfig


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def _snapshot_store_path(config: dict[str, Any]) -> str:
    return str(resolve_snapshot_store_path(config))


def _data_root(config: dict[str, Any]) -> str:
    return str(resolve_data_root(config))


def _build_snapshot_store(config: dict[str, Any]) -> Any:
    """Build the snapshot store per config["snapshot_store"]["backend"].

    Backends:
      - "duckdb" (default): legacy DuckDBSnapshotStore (sealed writes in SEAL phase)
      - "harvester": HarvesterSnapshotStore (Parquet under Data/harvester/snapshots/)
      - "dual": DualWriteSnapshotStore wrapping harvester (primary) + duckdb (secondary)

    The duckdb and harvester backends accept an explicit path override via
    config["snapshot_store"]["path"] (duckdb) or
    config["snapshot_store"]["harvester_path"] (harvester).
    """
    store_cfg = (config or {}).get("snapshot_store", {}) or {}
    backend = str(store_cfg.get("backend", "duckdb")).lower()

    if backend == "harvester":
        from src.data.harvester_snapshot_store import HarvesterSnapshotStore

        harvester_path = store_cfg.get("harvester_path")
        return HarvesterSnapshotStore(path=harvester_path, data_root=_data_root(config))

    if backend == "dual":
        from src.data.dual_write_snapshot_store import DualWriteSnapshotStore
        from src.data.harvester_snapshot_store import HarvesterSnapshotStore

        harvester_path = store_cfg.get("harvester_path")
        primary = HarvesterSnapshotStore(path=harvester_path, data_root=_data_root(config))
        secondary = DuckDBSnapshotStore(path=_snapshot_store_path(config), data_root=_data_root(config))
        return DualWriteSnapshotStore(primary=primary, secondary=secondary)

    # default: duckdb
    return DuckDBSnapshotStore(path=_snapshot_store_path(config), data_root=_data_root(config))


MAPPING_RULES_PATH: Path = WorkspacePaths.discover().data / "structural_lab" / "nlp" / "mapping_rules.yaml"


def _system_root(config: dict[str, Any]) -> Path:
    return Path(str((config.get("data") or {}).get("system_root", WorkspacePaths.discover().root))).expanduser()


def _build_composite_event_loader(
    file_loader,
    text_loader,
    nlp_translator: NLPEventTranslator | None = None,
):
    def loader() -> pd.DataFrame:
        file_events = file_loader() if file_loader is not None else pd.DataFrame()
        texts: list[dict[str, Any]] = []
        if text_loader is not None:
            try:
                texts = text_loader(run_date=None) or []
            except Exception:
                texts = []
        nlp_events = (
            nlp_translator.translate(texts)
            if nlp_translator is not None and texts
            else pd.DataFrame()
        )
        frames: list[pd.DataFrame] = [file_events]
        if not nlp_events.empty:
            frames.append(nlp_events)
        if len(frames) == 1:
            return frames[0]
        combined = pd.concat(frames, ignore_index=True)
        date_col = _resolve_date_column(combined)
        if date_col:
            combined[date_col] = pd.to_datetime(combined[date_col], errors="coerce")
            combined = combined.sort_values(date_col).reset_index(drop=True)
        return combined.drop_duplicates().reset_index(drop=True)

    return loader


def _resolve_date_column(frame: pd.DataFrame) -> str | None:
    for col in ("date", "event_date", "created_at"):
        if col in frame.columns:
            return col
    return None


def _build_event_loader(config: dict[str, Any]):
    event_path = _event_log_path(config)

    def loader() -> pd.DataFrame:
        if not event_path.exists():
            return pd.DataFrame(columns=["date", "channel", "event"])
        rows: list[dict[str, Any]] = []
        with event_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows.append(payload)
        if not rows:
            return pd.DataFrame(columns=["date", "channel", "event"])
        return pd.DataFrame.from_records(rows)

    return loader


def _build_recent_text_loader(config: dict[str, Any]):
    text_path = _text_log_path(config)

    def loader(run_date: str) -> list[dict[str, Any]]:
        _ = run_date
        if not text_path or str(text_path) in {".", ""} or not text_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with text_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
        return rows

    return loader


def _resolve_paths(config: dict[str, Any]) -> RuntimePaths:
    project_root = config.get("project_root")
    if project_root:
        return RuntimePaths.from_project_root(project_root)
    return RuntimePaths.discover()


def _event_log_path(config: dict[str, Any]) -> Path:
    explicit = config.get("event_log", {}).get("path")
    if explicit:
        return Path(explicit).expanduser()
    return _resolve_paths(config).event_log_path


def _text_log_path(config: dict[str, Any]) -> Path:
    return Path(config.get("text_log", {}).get("path", "")).expanduser()


def _resolve_data_backend(config: dict[str, Any]) -> str:
    """Resolve the active data backend from config.

    Priority: data_backend > data_access.backend > data.backend > default(legacy).
    """
    backend = config.get("data_backend")
    if backend is None:
        backend = (config.get("data_access") or {}).get("backend")
    if backend is None:
        backend = (config.get("data") or {}).get("backend")
    return str(backend or "harvester").strip().lower()


def _is_shadow_enabled(config: dict[str, Any]) -> bool:
    """Check if shadow mode is configured."""
    return bool(
        config.get("shadow_data_backend")
        or (config.get("data_access") or {}).get("shadow_backend")
    )


def build_system(config: dict[str, Any], use_mock: bool = True) -> ResearchPipeline:
    mechanism_cfg = config.get("mechanisms", {}) if isinstance(config.get("mechanisms", {}), dict) else {}
    mechanisms_enabled = _as_bool(mechanism_cfg.get("enabled", True), default=True)
    enabled_families = mechanism_cfg.get("enabled_families")
    if not isinstance(enabled_families, list):
        enabled_families = None
    operator_cfg = config.get("operators", {}) if isinstance(config.get("operators", {}), dict) else {}
    operators_enabled = _as_bool(operator_cfg.get("enabled", True), default=True)
    enabled_operator_families = operator_cfg.get("enabled_families")
    if not isinstance(enabled_operator_families, list):
        enabled_operator_families = None
    thresholds = build_thresholds(config)
    proxy_weights = build_proxy_weights(config)

    backend = _resolve_data_backend(config)

    # E.1: Config-guarded backend switch
    if backend == "harvester":
        data_hub = _build_harvester_data_hub(config, use_mock=use_mock)
        # If Harvester fails and fallback is allowed, use legacy
        if data_hub is None and _as_bool(config.get("allow_legacy_fallback", False)):
            _log_fallback_event(config, "Harvester backend failed; fallback to legacy DataHub.")
            data_hub = create_data_hub(config=config, use_mock=use_mock)
        elif data_hub is None:
            raise RuntimeError("Harvester backend failed and fallback is disabled.")
    else:
        # Legacy path — check freeze (F.1)
        if not use_mock:
            check_legacy_allowed("build_system")
        _warn_legacy_acquisition_used(
            config,
            reason=f"Configured data backend is {backend!r}; using legacy DataHub acquisition surface.",
            use_mock=use_mock,
        )
        data_hub = create_data_hub(config=config, use_mock=use_mock)

    data_source = DataHubBridge(hub=data_hub, fallback_seed=int(config.get("mock_seed", 42)))

    # D.2: Shadow mode — run DataHubLite in parallel for comparison
    if _is_shadow_enabled(config):
        _init_shadow_mode(config)
    mechanism_registry = (
        build_default_mechanism_registry(enabled_families=[str(x) for x in enabled_families])
        if mechanisms_enabled and enabled_families is not None
        else build_default_mechanism_registry()
        if mechanisms_enabled
        else None
    )
    operator_registry = (
        build_default_operator_registry(enabled_families=[str(x) for x in enabled_operator_families])
        if operators_enabled and enabled_operator_families is not None
        else build_default_operator_registry()
        if operators_enabled
        else None
    )

    file_event_loader = _build_event_loader(config)
    text_loader = _build_recent_text_loader(config)
    nlp_translator = None
    try:
        if MAPPING_RULES_PATH.exists():
            nlp_translator = NLPEventTranslator.from_mapping_rules(MAPPING_RULES_PATH)
    except Exception:
        pass

    snapshot_store = _build_snapshot_store(config)
    anomaly_detector, narrative_detector, reflexivity_detector = build_all_detectors(config, snapshot_store)

    return ResearchPipeline(
        data_source=data_source,
        proxy_builder=DefaultProxyBuilder(),
        ode_engine=ScipyODEEngine(mechanism_registry=mechanism_registry),
        singular_detector=ThresholdSingularDetector(
            sigma_threshold=thresholds.sigma,
            w_mismatch=proxy_weights.M,
            w_dof=proxy_weights.D,
            w_curvature=proxy_weights.K,
            w_shadow=proxy_weights.X,
            joint_hitting_enabled=thresholds.joint_hitting_enabled,
            dof_collapse_threshold=thresholds.dof_collapse,
            curvature_spike_threshold=thresholds.curvature_spike,
            forced_realization_threshold=thresholds.forced_realization,
        ),
        anomaly_detector=anomaly_detector,
        narrative_detector=narrative_detector,
        reflexivity_detector=reflexivity_detector,
        snapshot_store=snapshot_store,
        config=config,
        belief_builder=DefaultBeliefBuilder(sigma_threshold=thresholds.sigma),
        event_loader=_build_composite_event_loader(file_event_loader, text_loader, nlp_translator),
        recent_text_loader=text_loader,
        operator_registry=operator_registry,
    )


def _load_config(path: str = "config.yaml") -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle)
    if not isinstance(cfg, dict):
        return {}
    overlay_path = Path(__file__).resolve().parents[2] / "configs" / "detectors.yaml"
    if overlay_path.exists():
        with overlay_path.open("r", encoding="utf-8") as handle:
            extra = yaml.safe_load(handle) or {}
        if isinstance(extra, dict):
            cfg = {**cfg, **extra}
    return cfg


def _load_ml_signals(config: dict[str, Any]) -> dict[str, Any] | None:
    """Load supplementary ML context from Output/ml_signals/latest/.

    Returns None when ml_signals.enabled is False or signals are absent.
    This result is injected into config['ml_context'] before RunContext
    is built — it is NOT a proxy input and must NOT reach M/D/K/X channels.
    """
    try:
        from src.data_access.ml_signal_gateway import load_ml_signals
        ctx = load_ml_signals(config)
        return ctx.as_dict() if ctx is not None else None
    except Exception as exc:
        import logging
        logging.getLogger(__name__).debug("_load_ml_signals: skipped (%s)", exc)
        return None


def run_once(
    config: dict[str, Any],
    run_date: str | None = None,
    run_type: str | None = None,
    use_mock: bool = True,
) -> tuple[Snapshot, dict[str, str]]:
    ml_ctx = _load_ml_signals(config)
    if ml_ctx is not None:
        config = {**config, "ml_context": ml_ctx}

    pipeline = build_system(config, use_mock=use_mock)
    ctx = RunContext.from_config(config=config, run_date=run_date, run_type=run_type)
    snapshot = pipeline.run(ctx)

    paths = _resolve_paths(config)
    output_cfg = config.get("output", {})
    artifacts = export_snapshot_artifacts(
        snapshot=snapshot,
        output_dir=output_cfg.get("dir", str(paths.output_root)),
        export_image=bool(output_cfg.get("export_image", True)),
        image_width=int(output_cfg.get("image_width", 1400)),
    )
    return snapshot, artifacts


def build_fast_signal_computer(config: dict[str, Any]) -> FastSignalComputer:
    fast_cfg = config.get("fast_signal", {}) if isinstance(config.get("fast_signal", {}), dict) else {}
    raw_fred_dir = fast_cfg.get("raw_fred_dir")
    if raw_fred_dir is None:
        raw_fred_dir = _system_root(config) / "harvester" / "raw" / "fred"
    return FastSignalComputer(
        raw_fred_dir=raw_fred_dir,
        config=FastSignalConfig(
            baseline_days=int(fast_cfg.get("baseline_days", 364)),
            watch_threshold=float(fast_cfg.get("watch_threshold", 1.0)),
            warn_threshold=float(fast_cfg.get("warn_threshold", 1.5)),
            alert_threshold=float(fast_cfg.get("alert_threshold", 2.0)),
            min_observations=int(fast_cfg.get("min_observations", 60)),
            weights=fast_cfg.get("weights"),
        ),
    )


def run_fast_signal_once(config: dict[str, Any], run_date: str | None = None):
    computer = build_fast_signal_computer(config)
    signal = computer.compute(run_date or "9999-12-31")
    store = _build_snapshot_store(config)
    store.save_fast_signal(signal)

    validation = None
    if bool(config.get("_skip_fast_cross_validation", False)):
        return signal, validation
    canonical = store.load_latest_snapshot(signal.date, run_type="WEEKLY", inclusive=True)
    if canonical is not None:
        validation = CrossValidator().validate(canonical=canonical, fast=signal)
        store.save_cross_validation(validation)
    return signal, validation


def create_system_api(config: dict[str, Any], use_mock: bool = True) -> StructuralSystemAPI:
    pipeline = build_system(config, use_mock=use_mock)
    return StructuralSystemAPI(
        pipeline=pipeline,
        snapshot_store=pipeline.snapshot_store,
        data_source=pipeline.data_source,
        config=config,
        event_log_path=_event_log_path(config),
        evidence_store=RuntimeEvidenceStore(),
        data_hub=create_data_hub(config=config, use_mock=use_mock),
    )


def _build_harvester_data_hub(
    config: dict[str, Any],
    *,
    use_mock: bool = False,
) -> Any | None:
    """Build a DataHubLite wired to the Harvester adapter. Returns None on failure.

    In mock mode, falls back to creating a legacy DataHub with use_mock=True
    since tests don't have the full Harvester directory tree.
    """
    if use_mock:
        return create_data_hub(config=config, use_mock=True)

    try:
        from pathlib import Path

        from src.data.gateway.data_hub_lite import DataHubLite
        from src.data_access.harvester_adapter import HarvesterAdapter

        hcfg = config.get("harvester") or {}
        exports_root = hcfg.get("exports_root")
        if not exports_root:
            dacfg = config.get("data_access") or {}
            exports_root = dacfg.get("harvester_root") or dacfg.get("harvester_export_root")
        if not exports_root:
            exports_root = str(Path.cwd() / "Data" / "harvester" / "exports")

        contract_root = hcfg.get("contract_root", "")
        if not contract_root:
            contract_root = str(Path.cwd() / "Workbench" / "data_providers" /
                               "structural-risk-harvester" / "contracts")

        adapter = HarvesterAdapter(
            exports_root=Path(exports_root),
            release=str(hcfg.get("release", "latest")),
            contract_root=contract_root,
            require_finalized=True,
            validate_hashes=False,
            validate_schema=False,
        )
        return DataHubLite(adapter=adapter)
    except Exception:
        return None


def _init_shadow_mode(config: dict[str, Any]) -> None:
    """Initialize shadow mode — record intent but actual comparison
    happens at fetch time in the pipeline."""
    import logging
    logger = logging.getLogger(__name__)
    shadow_backend = config.get("shadow_data_backend") or (
        (config.get("data_access") or {}).get("shadow_backend", "harvester")
    )
    logger.info("Shadow mode active: primary=%s shadow=%s",
                _resolve_data_backend(config), shadow_backend)


def _log_fallback_event(config: dict[str, Any], message: str) -> None:
    """E.1.1: Log a fallback event to the System Learning Hub events directory."""
    import logging
    import warnings
    from datetime import UTC, datetime

    logger = logging.getLogger(__name__)
    logger.warning(message)
    warnings.warn(message, RuntimeWarning, stacklevel=2)

    # Write to system learning events if path exists
    events_dir = config.get("system_learning", {}).get("events_dir")
    if not events_dir:
        events_dir = "Output/system_learning/events"
    try:
        import json as _json
        from pathlib import Path
        edir = Path(events_dir)
        edir.mkdir(parents=True, exist_ok=True)
        event_file = edir / f"fallback_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        event_file.write_text(_json.dumps({
            "event_type": "backend_fallback",
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "from_backend": "harvester",
            "to_backend": "legacy",
            "message": message,
        }, indent=2) + "\n", encoding="utf-8")
    except (OSError, IOError) as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Failed to persist backend-fallback event to %s: %s", edir, exc
        )


def _warn_legacy_acquisition_used(config: dict[str, Any], *, reason: str, use_mock: bool) -> None:
    message = (
        "AUTHORITY CONFIG WARNING: legacy acquisition is active. "
        f"{reason} This is authority_config, not parameter_config."
    )
    warnings.warn(message, RuntimeWarning, stacklevel=2)


if __name__ == "__main__":
    loaded = _load_config()
    snapshot, artifacts = run_once(loaded, use_mock=True)
    print(snapshot)
    print("Artifacts:", artifacts)
