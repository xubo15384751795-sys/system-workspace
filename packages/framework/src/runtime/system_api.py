from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, cast

import numpy as np
import pandas as pd

from src.core.execution import RunContext
from src.core.interfaces import DataSource, PipelineInterface, SnapshotStoreInterface
from src.core.models import NarrativeReading, ProxyReading, Snapshot, StructuralState
from src.core.runtime_context import RuntimePaths
from src.data.gateway import DataHub
from src.interpretation.market_state import classify_pattern, leading_channel
from src.output.output_exporter import export_snapshot_artifacts, snapshot_to_dict
from src.runtime.assets import (
    AssetDefinition,
    asset_lineage,
    default_asset_catalog,
    materialize_snapshot_flow,
)
from src.runtime.evidence_store import RuntimeEvidenceStore

logger = logging.getLogger(__name__)


@dataclass
class StructuralSystemAPI:
    """
    Unified application-facing gateway for orchestrating Data + Core.

    Architectural contract:
    - Core owns judgment and state transitions.
    - Data owns acquisition, caching, and normalization.
    - Runtime owns orchestration and access.

    This object is the callable integration boundary for scripts, APIs, UI, and
    future automation layers. It intentionally consumes normalized protocol
    objects such as `RunContext` and `ProxyReading`, rather than raw upstream
    payloads or data-adapter internals.
    """

    pipeline: PipelineInterface
    snapshot_store: SnapshotStoreInterface
    data_source: DataSource
    config: dict[str, Any]
    event_log_path: Path | None = None
    asset_catalog: tuple[AssetDefinition, ...] = default_asset_catalog()
    evidence_store: RuntimeEvidenceStore | None = None
    data_hub: DataHub | None = None

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "project": self.config.get("project_name", "Structural Deformation Research System"),
            "data_mode": "mock" if self._is_mock_source() else "api",
            "series_ids": list(self.config.get("series_ids", [])),
        }

    def runtime(self) -> dict[str, Any]:
        data_cfg = self.config.get("data_sources", {})
        if not isinstance(data_cfg, dict):
            data_cfg = {}
        operator_cfg = self.config.get("operators", {})
        if not isinstance(operator_cfg, dict):
            operator_cfg = {}
        return {
            "data_sources": {
                "enabled": data_cfg.get("enabled", []),
                "composite_max_workers": data_cfg.get("composite_max_workers"),
                "fred_max_workers": data_cfg.get("fred_max_workers"),
                "fred_cache_dir": data_cfg.get("fred_cache_dir"),
                "proxy_incremental_cache": data_cfg.get("proxy_incremental_cache", True),
            },
            "operators": {
                "enabled": operator_cfg.get("enabled", True),
                "lookback_days": operator_cfg.get("lookback_days"),
                "max_events": operator_cfg.get("max_events"),
                "match_cache": True,
            },
            "boundaries": {
                "core": "judgment_and_state",
                "data": "acquisition_and_normalization",
                "runtime": "orchestration_and_access",
            },
            "assets": {
                "catalog_size": len(self.asset_catalog),
                "asset_model": "software_defined_assets",
            },
            "evidence_store": {
                "enabled": self.evidence_store is not None,
                "definition_count": len(self.evidence_store.definitions) if self.evidence_store is not None else 0,
            },
            "data_hub": {
                "enabled": self.data_hub is not None,
                "providers": self.data_hub.available_providers() if self.data_hub is not None else {},
                "structural_preset_count": len(self.data_hub.structural_presets) if self.data_hub is not None else 0,
            },
        }

    def available_series(self) -> list[str]:
        try:
            return cast(list[str], self.data_source.available_series())
        except Exception as exc:
            logger.warning(
                "Data source series discovery failed: error_type=%s",
                type(exc).__name__,
            )
            return []

    def fetch_data(self, series_ids: list[str], start: str, end: str) -> dict[str, Any]:
        frame = self.data_source.fetch(series_ids=series_ids, start=start, end=end)
        return {
            "start": start,
            "end": end,
            "columns": list(frame.columns),
            "rows": [
                {"date": idx.strftime("%Y-%m-%d"), **{col: _json_value(row[col]) for col in frame.columns}}
                for idx, row in frame.iterrows()
            ],
        }

    def available_data_providers(self) -> dict[str, list[str]]:
        return self.data_hub.available_providers() if self.data_hub is not None else {}

    def available_structural_presets(self) -> list[dict[str, Any]]:
        return self.data_hub.available_structural_presets() if self.data_hub is not None else []

    def provider_capabilities(self) -> list[dict[str, Any]]:
        return self.data_hub.provider_capabilities() if self.data_hub is not None else []

    def route_evidence(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if self.data_hub is None:
            raise RuntimeError("data hub is not configured")
        return cast(dict[str, Any], self.data_hub.route_evidence(request))

    def fetch_structural_presets(self, preset_names: Sequence[str], start: str, end: str) -> dict[str, Any]:
        if self.data_hub is None:
            raise RuntimeError("data hub is not configured")
        return cast(dict[str, Any], self.data_hub.fetch_structural_presets(preset_names, start=start, end=end).to_dict())

    def fetch_series(self, requests: Sequence[Mapping[str, Any]], start: str, end: str) -> dict[str, Any]:
        if self.data_hub is None:
            raise RuntimeError("data hub is not configured")
        return cast(dict[str, Any], self.data_hub.fetch_series(requests, start=start, end=end).to_dict())

    def fetch_events(self, requests: Sequence[Mapping[str, Any]], start: str, end: str) -> dict[str, Any]:
        if self.data_hub is None:
            raise RuntimeError("data hub is not configured")
        return cast(dict[str, Any], self.data_hub.fetch_events(requests, start=start, end=end).to_dict())

    def fetch_filings(self, requests: Sequence[Mapping[str, Any]], start: str, end: str) -> dict[str, Any]:
        if self.data_hub is None:
            raise RuntimeError("data hub is not configured")
        return cast(dict[str, Any], self.data_hub.fetch_filings(requests, start=start, end=end).to_dict())

    def fetch_positions(self, requests: Sequence[Mapping[str, Any]], start: str, end: str) -> dict[str, Any]:
        if self.data_hub is None:
            raise RuntimeError("data hub is not configured")
        return cast(dict[str, Any], self.data_hub.fetch_positions(requests, start=start, end=end).to_dict())

    def run_snapshot(
        self,
        run_date: str | RunContext,
        run_type: str = "WEEKLY",
        export_artifacts: bool = False,
    ) -> dict[str, Any]:
        snapshot = self.pipeline.run(run_date=run_date, run_type=run_type)
        payload = cast(dict[str, Any], snapshot_to_dict(snapshot))
        payload["assets"] = [
            {
                "asset_name": item.asset_name,
                "layer": next((asset.layer for asset in self.asset_catalog if asset.asset_name == item.asset_name), "unknown"),
                "creation_mode": item.creation_mode,
                "quality_status": item.quality_status,
                "upstream_assets": list(item.upstream_assets),
            }
            for item in materialize_snapshot_flow(
                catalog=self.asset_catalog,
                run_date=snapshot.run_date,
                creation_mode=self._creation_mode(run_type),
                provenance=snapshot.state.provenance,
                include_export=export_artifacts,
            )
        ]
        if self.evidence_store is not None:
            payload["evidence"] = self.get_snapshot_evidence(snapshot.run_date)
        if export_artifacts:
            payload["artifacts"] = self.export_snapshot(snapshot.run_date)
        return payload

    def run_context(self, ctx: RunContext, export_artifacts: bool = False) -> dict[str, Any]:
        return self.run_snapshot(run_date=ctx, export_artifacts=export_artifacts)

    def submit_candidates(
        self,
        candidates: Sequence[ProxyReading] | ProxyReading,
        run_type: str = "CANDIDATE",
        persist: bool = False,
    ) -> list[dict[str, Any]]:
        items = [candidates] if isinstance(candidates, ProxyReading) else list(candidates)
        return [snapshot_to_dict(self._evaluate_proxy(proxy, run_type=run_type, persist=persist)) for proxy in items]

    def submit_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        normalized = _normalize_event_payload(event)
        if self.event_log_path is None:
            raise RuntimeError("event log path is not configured")
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, ensure_ascii=True) + "\n")

        if hasattr(self.snapshot_store, "upsert_event_log"):
            try:
                frame = pd.DataFrame.from_records([normalized])
                getattr(self.snapshot_store, "upsert_event_log")(frame)
            except Exception as exc:
                import logging

                logging.getLogger(__name__).debug(
                    "Event log upsert skipped for event %s: %s",
                    normalized.get("run_date", "unknown"),
                    exc,
                )
        return normalized

    def get_snapshot(self, run_date: str) -> dict[str, Any] | None:
        snapshot = self.snapshot_store.load(run_date)
        return snapshot_to_dict(snapshot) if snapshot is not None else None

    def list_snapshots(self, start: str = "1900-01-01", end: str = "2999-12-31") -> list[dict[str, Any]]:
        snapshots = self.snapshot_store.load_range(start, end)
        return [
            {
                "run_date": snap.run_date,
                "run_type": snap.run_type,
                "sigma_t": snap.state.sigma_t,
                "singular_flag": snap.state.singular_flag,
                "pattern": snap.state.pattern,
                "escalation": snap.escalation,
            }
            for snap in snapshots
        ]

    def replay_window(self, start: str, end: str) -> dict[str, Any]:
        snapshots = self.snapshot_store.load_range(start, end)
        return {
            "start": start,
            "end": end,
            "count": len(snapshots),
            "snapshots": [snapshot_to_dict(snapshot) for snapshot in snapshots],
        }

    def describe_assets(self) -> list[dict[str, Any]]:
        return [
            {
                "asset_name": item.asset_name,
                "layer": item.layer,
                "description": item.description,
                "upstream_assets": list(item.upstream_assets),
                "version": item.version,
                "checks": list(item.checks),
                "metadata": dict(item.metadata),
            }
            for item in self.asset_catalog
        ]

    def asset_lineage(self, asset_name: str) -> dict[str, Any] | None:
        return cast(dict[str, Any] | None, asset_lineage(self.asset_catalog, asset_name))

    def list_evidence_definitions(self) -> list[dict[str, Any]]:
        if self.evidence_store is None:
            return []
        return cast(list[dict[str, Any]], self.evidence_store.list_definitions())

    def get_snapshot_evidence(self, run_date: str, refresh: bool = False) -> dict[str, Any] | None:
        if self.evidence_store is None:
            return None
        snapshot = self.snapshot_store.load(run_date)
        if snapshot is None:
            return None
        history_start = str(self.config.get("history_start", run_date))
        history = self.snapshot_store.load_range(history_start, run_date)
        prior = [item for item in history if item.run_date != run_date]
        bundle = self.evidence_store.build_snapshot_bundle(snapshot=snapshot, history=prior, refresh=refresh)
        result = {
            "run_date": bundle.run_date,
            "target_type": bundle.target_type,
            "families": {name: dict(values) for name, values in bundle.families.items()},
            "metadata": dict(bundle.metadata),
        }
        if bundle.canonical_chain is not None:
            result["canonical_chain"] = dict(bundle.canonical_chain)
            result["canonical_ids"] = {
                "observation_id": bundle.canonical_chain["observation"]["observation_id"],
                "measurement_id": bundle.canonical_chain["measurement"]["measurement_id"],
                "evidence_id": bundle.canonical_chain["evidence"]["evidence_id"],
                "claim_id": bundle.canonical_chain["claim"]["claim_id"],
            }
        return result

    def export_snapshot(self, run_date: str) -> dict[str, str] | None:
        snapshot = self.snapshot_store.load(run_date)
        if snapshot is None:
            return None
        output_cfg = self.config.get("output", {})
        return cast(dict[str, str] | None, export_snapshot_artifacts(
            snapshot=snapshot,
            output_dir=str(output_cfg.get("dir", str(RuntimePaths.discover().output_root))),
            export_image=bool(output_cfg.get("export_image", True)),
            image_width=int(output_cfg.get("image_width", 1400)),
        ))

    def _evaluate_proxy(self, proxy: ProxyReading, run_type: str, persist: bool) -> Snapshot:
        pipeline = self.pipeline
        params = pipeline._ode_params() if hasattr(pipeline, "_ode_params") else {}
        z = pipeline.ode_engine.integrate(proxy, params)
        z = np.asarray(z, dtype=float) if isinstance(z, np.ndarray) else np.zeros(6, dtype=float)
        if z.shape[0] == 0 or not np.all(np.isfinite(z)):
            z = np.zeros(6, dtype=float)

        belief_state = None
        if getattr(pipeline, "belief_builder", None) is not None and hasattr(pipeline, "_load_previous_belief"):
            belief_state = pipeline.belief_builder.build(  # type: ignore[union-attr]
                proxy,
                previous_belief=pipeline._load_previous_belief(proxy.run_date),
                operator_diagnostics=None,
            )

        sigma_t, singular_flag = pipeline.singular_detector.detect(proxy, z, belief_state=belief_state)
        detector_diagnostics = getattr(pipeline.singular_detector, "last_diagnostics", None)
        structural_singular_time = None
        if detector_diagnostics is not None:
            structural_singular_time = getattr(detector_diagnostics, "structural_singular_time", None)
        anomaly_score = self._safe_call(pipeline.anomaly_detector.score, proxy)
        narrative = self._safe_call(pipeline.narrative_detector.analyze, [], proxy.run_date)
        if narrative is None:
            narrative = NarrativeReading(
                run_date=proxy.run_date,
                ai_unicorn="ANCHORED",
                clo_cmbs="ANCHORED",
                policy="ANCHORED",
                drift_scores={"ai_unicorn": 0.0, "clo_cmbs": 0.0, "policy": 0.0},
            )
        reflexivity_flags = {"credit": False, "liquidity": False, "policy": False}
        pattern = classify_pattern(proxy.directions, reflexivity_flags)
        state = StructuralState(
            run_date=proxy.run_date,
            z_vector=z,
            sigma_t=sigma_t,
            singular_flag=singular_flag,
            leading_channel=leading_channel(proxy.directions),
            pattern=pattern,
            anomaly_score=anomaly_score,
            reflexivity_flags=reflexivity_flags,
            provenance=pipeline._build_provenance(proxy.run_date) if hasattr(pipeline, "_build_provenance") else {},
            operator_diagnostics=None,
            belief_state=belief_state,
            structural_singular_time=structural_singular_time,
        )
        snapshot = Snapshot(
            run_date=proxy.run_date,
            run_type=run_type,
            proxy=proxy,
            state=state,
            narrative=narrative,
            escalation=bool(singular_flag),
            escalation_reason="Candidate evaluation exceeded singular threshold" if singular_flag else None,
        )
        if persist:
            self.snapshot_store.save(snapshot)
        return snapshot

    def _safe_call(self, fn, *args):
        try:
            return fn(*args)
        except Exception:
            return None

    def _is_mock_source(self) -> bool:
        return type(self.data_source).__name__ == "MockDataSource"

    def _creation_mode(self, run_type: str) -> str:
        name = str(run_type).upper()
        if "SIM" in name:
            return "simulation"
        if "REPLAY" in name:
            return "replay"
        if "MANUAL" in name or "CANDIDATE" in name:
            return "manual"
        return "live"


def _json_value(value: Any) -> Any:
    try:
        if value != value:
            return None
    except Exception:
        return value
    if hasattr(value, "item"):
        return value.item()
    return value


def _normalize_event_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    normalized = {str(key): _json_value(value) for key, value in dict(event).items()}
    if "affected_proxy" in normalized and isinstance(normalized["affected_proxy"], tuple):
        normalized["affected_proxy"] = list(normalized["affected_proxy"])
    return normalized
