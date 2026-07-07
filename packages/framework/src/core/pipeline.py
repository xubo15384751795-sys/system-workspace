from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from src.core.interfaces import (
    AnomalyDetectorInterface,
    BeliefBuilderInterface,
    DataSource,
    NarrativeDetectorInterface,
    PipelineInterface,
    ProxyBuilderInterface,
    ReflexivityDetectorInterface,
    SnapshotStoreInterface,
    SingularDetectorInterface,
    ODEEngineInterface,
)
from src.core.execution import DiagnosticBundle, RunContext
from src.core.models import Snapshot, StructuralBeliefState, StructuralState
from src.core.models import StructuralDiagnosticState
from src.core.pipeline_stages import PipelineRunPolicy, PipelineStage
from src.operators.operator_schema import OperatorDiagnostics
from src.core.provenance import build_provenance
from src.data.contracts import StructuralFetchPlan, build_structural_fetch_plan
from src.data.gateway.evidence_router import EvidenceRouter
from src.data.distribution.summary import ChannelDistributionState
from src.data.quality.manifest import QUALITY_MOCK, DataEvidenceManifest
from src.derivation.structural_layers import StructuralLayerBundle, build_structural_layers
from src.diagnostics.structural_diagnostic import build_structural_diagnostic_state
from src.interpretation.market_state import classify_pattern, leading_channel
from src.operators.event_to_operator import apply_event_log_to_proxy
from src.operators.operator_registry import StructuralOperatorRegistry


class ResearchPipeline(PipelineInterface):
    def __init__(
        self,
        data_source: DataSource,
        proxy_builder: ProxyBuilderInterface,
        ode_engine: ODEEngineInterface,
        singular_detector: SingularDetectorInterface,
        anomaly_detector: AnomalyDetectorInterface,
        narrative_detector: NarrativeDetectorInterface,
        reflexivity_detector: ReflexivityDetectorInterface,
        snapshot_store: SnapshotStoreInterface,
        config: dict[str, Any],
        belief_builder: BeliefBuilderInterface | None = None,
        event_loader: Callable[[], pd.DataFrame] | None = None,
        recent_text_loader: Callable[[str], list[dict[str, Any]]] | None = None,
        operator_registry: StructuralOperatorRegistry | None = None,
    ) -> None:
        self.data_source = data_source
        self.proxy_builder = proxy_builder
        self.ode_engine = ode_engine
        self.singular_detector = singular_detector
        self.anomaly_detector = anomaly_detector
        self.narrative_detector = narrative_detector
        self.reflexivity_detector = reflexivity_detector
        self.snapshot_store = snapshot_store
        self.config = config
        self.belief_builder = belief_builder
        self.event_loader = event_loader
        self.recent_text_loader = recent_text_loader
        self.operator_registry = operator_registry
        self.run_policy = PipelineRunPolicy.from_config(config)

    def run(self, run_date: str | RunContext, run_type: str = "WEEKLY") -> Snapshot:
        ctx = self._coerce_run_context(run_date, run_type)
        cached = self._load_cached_snapshot(ctx)
        if cached is not None:
            return cached
        stages: list[str] = []
        structural_plan = self._resolve_structural_plan(ctx)
        stages.append(PipelineStage.EVIDENCE_ACQUISITION.value)
        raw = self.data_source.fetch(
            series_ids=list(ctx.series_ids),
            start=ctx.history_start,
            end=ctx.run_date,
        )

        # Read evidence manifest from DataHubBridge if available.
        evidence_manifest: DataEvidenceManifest | None = getattr(
            self.data_source, "last_evidence_manifest", None
        )
        if evidence_manifest is not None and evidence_manifest.any_fallback:
            self._log_warning(
                f"data quality degraded: research_quality={evidence_manifest.research_quality}, "
                f"fallback channels={evidence_manifest.channels_with_fallback()}, "
                f"fallback series={[r.series_id for r in evidence_manifest.fallback_series()]}"
            )

        provenance = self._build_provenance(
            ctx.run_date,
            ctx=ctx,
            raw=raw,
            structural_plan=structural_plan,
            evidence_manifest=evidence_manifest,
        )
        provenance["pipeline_policy"] = self.run_policy.stage_manifest()
        proxy = self.proxy_builder.build(raw, ctx.run_date)
        stages.append(PipelineStage.PROXY_CONSTRUCTION.value)

        # Compute distributional state from raw proxy history window.
        distribution_state = self._build_distribution_state(raw, ctx.run_date)
        if distribution_state is not None:
            provenance["distribution_state"] = distribution_state.to_dict()

        if self._proxy_too_incomplete(proxy):
            return self._escalate(ctx, proxy, "Proxy data too incomplete to proceed", provenance=provenance)

        # Escalate if all data is mock — research interpretation would be invalid.
        if evidence_manifest is not None and evidence_manifest.research_quality == QUALITY_MOCK:
            return self._escalate(
                ctx, proxy,
                "All channel data is mock/fallback — research interpretation suppressed",
                provenance=provenance,
            )

        event_log = self._load_event_log()
        proxy, operator_diagnostics = self._apply_structural_operators(proxy, event_log, ctx.run_date)
        belief_state = (
            self._build_belief_state(ctx.run_date, proxy, operator_diagnostics)
            if self.run_policy.run_belief_extension
            else None
        )
        structural_layers = self._build_structural_layers(proxy, operator_diagnostics)

        z = self.ode_engine.integrate(proxy, self._ode_params(), operator_hints=operator_diagnostics)
        if not isinstance(z, np.ndarray) or z.shape[0] == 0:
            return self._escalate(
                ctx,
                proxy,
                "ODE integration returned invalid state",
                operator_diagnostics=operator_diagnostics,
                belief_state=belief_state,
                structural_layers=structural_layers,
                provenance=provenance,
            )
        if not np.all(np.isfinite(z)):
            self._log_warning("ODE integration returned non-finite values; escalating run")
            return self._escalate(
                ctx,
                proxy,
                "ODE integration produced non-finite values",
                operator_diagnostics=operator_diagnostics,
                belief_state=belief_state,
                structural_layers=structural_layers,
                provenance=provenance,
            )

        provenance["primitive_state"] = structural_layers.primitive_state.to_dict()
        provenance["shadow_mass_state"] = structural_layers.shadow_mass_state.to_dict()
        provenance["mean_field_gap"] = structural_layers.mean_field_gap.to_dict()
        solver_diagnostics = getattr(self.ode_engine, "last_diagnostics", None)
        structural_singular_time = None
        if solver_diagnostics is not None and hasattr(solver_diagnostics, "to_dict"):
            solver_payload = solver_diagnostics.to_dict()
            provenance["ode_solver"] = solver_payload
            structural_singular_time = solver_payload.get("threshold_hit_time")

        sigma_t, singular_flag = self.singular_detector.detect(
            proxy,
            z,
            op_diag=operator_diagnostics,
            belief_state=belief_state,
            shadow_mass_state=structural_layers.shadow_mass_state,
        )
        diagnostic_state = build_structural_diagnostic_state(
            run_date=ctx.run_date,
            proxy=proxy,
            sigma_t=sigma_t,
            raw_history=raw,
        )
        stages.append(PipelineStage.PAPER_DIAGNOSTICS.value)
        detector_diagnostics = getattr(self.singular_detector, "last_diagnostics", None)
        if detector_diagnostics is not None and hasattr(detector_diagnostics, "to_dict"):
            detector_payload = detector_diagnostics.to_dict()
            provenance["singular_detector"] = detector_payload
            if structural_singular_time is None:
                structural_singular_time = detector_payload.get("structural_singular_time")
        provenance["structural_singular_time"] = structural_singular_time
        provenance["structural_diagnostic_state"] = diagnostic_state.to_dict()
        if singular_flag:
            return self._escalate(
                ctx,
                proxy,
                "Singular regime flag triggered",
                operator_diagnostics=operator_diagnostics,
                belief_state=belief_state,
                structural_layers=structural_layers,
                provenance=provenance,
                structural_singular_time=structural_singular_time,
            )

        anomaly_score = self._safe_run(self.anomaly_detector.score, proxy) if self.run_policy.run_ml_extensions else None
        proxy_history = self._load_proxy_history(ctx.run_date)
        reflexivity_flags = (
            self._safe_run(self.reflexivity_detector.check, event_log, proxy_history, ctx.run_date)
            if self.run_policy.run_ml_extensions
            else {}
        )
        if self._multi_reflexivity(reflexivity_flags):
            return self._escalate(
                ctx,
                proxy,
                "Multi-channel reflexivity detected",
                operator_diagnostics=operator_diagnostics,
                belief_state=belief_state,
                provenance=provenance,
            )

        texts = self._load_recent_texts(ctx.run_date) if self.run_policy.run_narrative_extension else []
        narrative = (
            self._safe_run(self.narrative_detector.analyze, texts, ctx.run_date)
            if self.run_policy.run_narrative_extension
            else None
        )
        if self.run_policy.run_narrative_extension and narrative is None:
            return self._escalate(ctx, proxy, "Narrative detector returned no reading", provenance=provenance)
        if self.run_policy.run_extensions:
            stages.append(PipelineStage.EXPLORATORY_EXTENSIONS.value)

        diagnostics = DiagnosticBundle(
            z_vector=z,
            sigma_t=sigma_t,
            singular_flag=singular_flag,
            anomaly_score=anomaly_score,
            reflexivity_flags=reflexivity_flags or {},
            operator_diagnostics=operator_diagnostics,
            narrative=narrative,
            leading_channel=leading_channel(proxy.directions),
            pattern=classify_pattern(proxy.directions, reflexivity_flags or {}),
        )

        # Embed distribution state and evidence manifest in provenance so
        # they flow through to the snapshot without changing the frozen model.
        if distribution_state is not None:
            provenance["distribution_state"] = distribution_state.to_dict()
        if evidence_manifest is not None:
            provenance["evidence_manifest"] = evidence_manifest.to_dict()
        stages.append(PipelineStage.ENGINEERING_AUDIT.value)
        stages.append(PipelineStage.SNAPSHOT_ASSEMBLY.value)
        provenance["pipeline_stages"] = stages

        state = StructuralState(
            run_date=ctx.run_date,
            z_vector=diagnostics.z_vector,
            sigma_t=diagnostics.sigma_t,
            singular_flag=diagnostics.singular_flag,
            leading_channel=diagnostics.leading_channel,
            pattern=diagnostics.pattern,
            anomaly_score=diagnostics.anomaly_score if self.run_policy.persist_extension_outputs else None,
            reflexivity_flags=diagnostics.reflexivity_flags if self.run_policy.persist_extension_outputs else {},
            provenance=provenance,
            operator_diagnostics=operator_diagnostics,
            belief_state=belief_state if self.run_policy.persist_extension_outputs else None,
            primitive_state=structural_layers.primitive_state,
            shadow_mass_state=structural_layers.shadow_mass_state,
            mean_field_gap=structural_layers.mean_field_gap,
            diagnostic_state=diagnostic_state,
            structural_singular_time=structural_singular_time,
        )

        snapshot = Snapshot(
            run_date=ctx.run_date,
            run_type=ctx.run_type,
            proxy=proxy,
            state=state,
            narrative=diagnostics.narrative if self.run_policy.persist_extension_outputs else None,
            escalation=diagnostics.escalation,
            escalation_reason=diagnostics.escalation_reason,
        )
        self.snapshot_store.save(snapshot)
        return snapshot

    def _safe_run(self, fn, *args):
        try:
            return fn(*args)
        except Exception as exc:
            self._log_warning(f"{fn.__name__} failed: {exc}")
            return None

    def _load_cached_snapshot(self, ctx: RunContext) -> Snapshot | None:
        pipeline_cfg = self.config.get("pipeline", {})
        if not isinstance(pipeline_cfg, dict) or not bool(pipeline_cfg.get("reuse_existing_snapshot", False)):
            return None
        try:
            snapshot = self.snapshot_store.load(ctx.run_date)
        except Exception as exc:
            self._log_warning(f"snapshot cache lookup failed: {exc}")
            return None
        if snapshot is None or snapshot.run_type != ctx.run_type:
            return None
        return snapshot

    def _escalate(
        self,
        ctx: RunContext,
        proxy,
        reason: str,
        operator_diagnostics: OperatorDiagnostics | None = None,
        belief_state: StructuralBeliefState | None = None,
        structural_layers: StructuralLayerBundle | None = None,
        provenance: dict | None = None,
        structural_singular_time: float | None = None,
    ) -> Snapshot:
        if structural_layers is not None:
            provenance = dict(provenance or self._build_provenance(ctx.run_date, ctx=ctx, structural_plan=self._resolve_structural_plan(ctx)))
            provenance.setdefault("primitive_state", structural_layers.primitive_state.to_dict())
            provenance.setdefault("shadow_mass_state", structural_layers.shadow_mass_state.to_dict())
            provenance.setdefault("mean_field_gap", structural_layers.mean_field_gap.to_dict())
        provenance = dict(provenance or self._build_provenance(ctx.run_date, ctx=ctx, structural_plan=self._resolve_structural_plan(ctx)))
        provenance.setdefault("pipeline_policy", self.run_policy.stage_manifest())
        provenance.setdefault("pipeline_stages", [PipelineStage.SNAPSHOT_ASSEMBLY.value])
        diagnostic_payload = provenance.get("structural_diagnostic_state")
        diagnostic_state = (
            StructuralDiagnosticState.from_dict(diagnostic_payload)
            if isinstance(diagnostic_payload, dict)
            else None
        )
        diagnostics = DiagnosticBundle(
            z_vector=None,
            sigma_t=None,
            singular_flag=None,
            anomaly_score=None,
            reflexivity_flags={},
            operator_diagnostics=operator_diagnostics,
            narrative=None,
            escalation=True,
            escalation_reason=reason,
        )
        snapshot = Snapshot(
            run_date=ctx.run_date,
            run_type=ctx.run_type,
            proxy=proxy,
            state=StructuralState(
                run_date=ctx.run_date,
                z_vector=diagnostics.z_vector,
                sigma_t=diagnostics.sigma_t,
                singular_flag=diagnostics.singular_flag,
                leading_channel=diagnostics.leading_channel,
                pattern=diagnostics.pattern,
                anomaly_score=diagnostics.anomaly_score,
                reflexivity_flags=diagnostics.reflexivity_flags,
                provenance=provenance,
                operator_diagnostics=diagnostics.operator_diagnostics,
                belief_state=belief_state,
                primitive_state=structural_layers.primitive_state if structural_layers is not None else None,
                shadow_mass_state=structural_layers.shadow_mass_state if structural_layers is not None else None,
                mean_field_gap=structural_layers.mean_field_gap if structural_layers is not None else None,
                diagnostic_state=diagnostic_state,
                structural_singular_time=structural_singular_time,
            ),
            narrative=diagnostics.narrative,
            escalation=diagnostics.escalation,
            escalation_reason=diagnostics.escalation_reason,
        )
        self.snapshot_store.save(snapshot)
        return snapshot

    def _build_structural_layers(
        self,
        proxy,
        operator_diagnostics: OperatorDiagnostics | None,
    ) -> StructuralLayerBundle:
        cfg = self.config.get("structural_layers", {})
        cfg = cfg if isinstance(cfg, dict) else {}
        shadow_cfg = self.config.get("shadow_mass", {})
        if isinstance(shadow_cfg, dict):
            cfg = {**cfg, **shadow_cfg}
        try:
            return build_structural_layers(proxy, operator_diagnostics=operator_diagnostics, config=cfg)
        except Exception as exc:
            self._log_warning(f"structural layer derivation failed: {exc}")
            return build_structural_layers(proxy, operator_diagnostics=None, config={})

    def _build_belief_state(
        self,
        run_date: str,
        proxy,
        operator_diagnostics: OperatorDiagnostics | None = None,
    ) -> StructuralBeliefState | None:
        if self.belief_builder is None:
            return None
        previous_belief = self._load_previous_belief(run_date)
        try:
            return self.belief_builder.build(
                proxy,
                previous_belief=previous_belief,
                operator_diagnostics=operator_diagnostics,
            )
        except Exception as exc:
            self._log_warning(f"belief builder failed: {exc}")
            return None

    def _load_previous_belief(self, run_date: str) -> StructuralBeliefState | None:
        latest = self.snapshot_store.load_latest_before(run_date)
        if latest is None:
            return None
        return latest.state.belief_state

    def _coerce_run_context(self, run_date: str | RunContext, run_type: str) -> RunContext:
        if isinstance(run_date, RunContext):
            return RunContext(
                run_date=self._normalize_run_date(run_date.run_date),
                run_type=run_date.run_type,
                history_start=run_date.history_start,
                series_ids=run_date.series_ids,
                config=dict(run_date.config),
            )
        return RunContext.from_config(
            config=self.config,
            run_date=self._normalize_run_date(run_date),
            run_type=run_type,
        )

    def _proxy_too_incomplete(self, proxy) -> bool:
        available_count = sum(proxy.available.values())
        return available_count < 2

    def _multi_reflexivity(self, flags: dict[str, bool] | None) -> bool:
        if not flags:
            return False
        return sum(flags.values()) >= 2

    def _leading_channel(self, directions: dict[str, str] | Any) -> str:
        return leading_channel(directions)

    def _classify_pattern(self, directions: dict[str, str], reflexivity_flags: dict[str, bool]) -> str:
        return classify_pattern(directions, reflexivity_flags)

    def _build_distribution_state(
        self,
        raw: pd.DataFrame | None,
        run_date: str,
    ) -> ChannelDistributionState | None:
        if raw is None or raw.empty:
            return None
        try:
            return ChannelDistributionState.build(
                frame=raw,
                window_label=f"{len(raw)}obs",
                as_of=run_date,
            )
        except Exception as exc:
            self._log_warning(f"distribution state computation failed: {exc}")
            return None

    def _build_provenance(
        self,
        run_date: str,
        ctx: RunContext | None = None,
        raw: pd.DataFrame | None = None,
        structural_plan: StructuralFetchPlan | None = None,
        evidence_manifest: DataEvidenceManifest | None = None,
    ) -> dict[str, Any]:
        provenance = build_provenance(self.config, run_date)
        usage_manifest = self._data_usage_manifest(ctx=ctx, raw=raw, structural_plan=structural_plan)
        if usage_manifest is not None:
            provenance["datahub_manifest"] = usage_manifest
        # Embed evidence manifest at top level for quick access
        if evidence_manifest is not None:
            provenance["data_quality"] = {
                "research_quality": evidence_manifest.research_quality,
                "any_fallback": evidence_manifest.any_fallback,
                "channels_with_fallback": evidence_manifest.channels_with_fallback(),
                "real_series": evidence_manifest.real_series,
                "total_series": evidence_manifest.total_series,
            }
        if structural_plan is not None:
            router = EvidenceRouter()
            provenance["evidence_routes"] = {
                series_id: route.to_dict()
                for series_id, route in router.route_proxy_series(structural_plan.requested_series_ids).items()
            }
        return provenance

    def _data_usage_manifest(
        self,
        ctx: RunContext | None = None,
        raw: pd.DataFrame | None = None,
        structural_plan: StructuralFetchPlan | None = None,
    ) -> dict[str, Any] | None:
        metadata = getattr(self.data_source, "last_fetch_metadata", None)
        if not isinstance(metadata, dict) and structural_plan is None:
            return None
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        providers_touched = metadata.get("providers_touched", [])
        provider_runs = metadata.get("provider_runs", [])
        plan = structural_plan or self._resolve_structural_plan(ctx)
        request_to_presets = plan.request_to_presets() if plan is not None else {}
        enriched_provider_runs: list[dict[str, Any]] = []
        if isinstance(provider_runs, list):
            for item in provider_runs:
                if not isinstance(item, dict):
                    continue
                request_keys = list(item.get("request_keys", []))
                preset_names = sorted(
                    {
                        preset_name
                        for request_key in request_keys
                        for preset_name in request_to_presets.get(request_key, ())
                    }
                )
                enriched = dict(item)
                enriched["preset_names"] = preset_names
                enriched_provider_runs.append(enriched)
        return {
            "manifest_version": "1.0",
            "lineage_mode": metadata.get("lineage_mode", "data_source_bridge"),
            "run_scope": {
                "run_date": ctx.run_date if ctx is not None else None,
                "history_start": ctx.history_start if ctx is not None else None,
                "series_ids": list(ctx.series_ids) if ctx is not None else [],
            },
            "structural_targets": list(plan.channels_touched) if plan is not None else [],
            "preset_names": list(plan.preset_names) if plan is not None else [],
            "channels_touched": list(plan.channels_touched) if plan is not None else [],
            "blocks_touched": list(plan.blocks_touched) if plan is not None else [],
            "measurement_blocks": list(plan.blocks_touched) if plan is not None else [],
            "evidence_roles": list(plan.evidence_roles) if plan is not None else [],
            "request_count": int(metadata.get("request_count", 0)),
            "providers_touched": list(providers_touched) if isinstance(providers_touched, list) else [],
            "request_lineage": {
                "requested_series_ids": list(metadata.get("requested_series_ids", list(plan.requested_series_ids if plan is not None else ()))),
                "expanded_series_ids": list(metadata.get("expanded_series_ids", list(plan.expanded_request_keys if plan is not None else ()))),
                "request_keys": list(metadata.get("request_keys", list(plan.expanded_request_keys if plan is not None else ()))),
                "unresolved_series_ids": list(plan.unresolved_series_ids) if plan is not None else [],
            },
            "response_stats": {
                "row_count": int(metadata.get("row_count", len(raw) if raw is not None else 0)),
                "column_count": int(metadata.get("column_count", len(raw.columns) if raw is not None else 0)),
                "success_count": int(metadata.get("success_count", 0)),
                "failure_count": int(metadata.get("failure_count", 0)),
                "fallback_used": bool(metadata.get("fallback_used", False)),
                "latency_ms": metadata.get("latency_ms"),
            },
            "source_identity": {
                "source_type": str(metadata.get("source_type", type(self.data_source).__name__)),
                "provider_runs": enriched_provider_runs,
            },
        }

    def _resolve_structural_plan(self, ctx: RunContext | None) -> StructuralFetchPlan:
        if ctx is None:
            return build_structural_fetch_plan(series_ids=())
        plan = build_structural_fetch_plan(series_ids=ctx.series_ids)
        if plan.unresolved_series_ids:
            unresolved = ", ".join(plan.unresolved_series_ids)
            raise ValueError(f"structural evidence admission failed for series_ids: {unresolved}")
        return plan

    def _load_proxy_history(self, run_date: str) -> pd.DataFrame:
        records = []
        for snapshot in self.snapshot_store.iter_range(self.config["history_start"], run_date):
            records.append(
                {
                    "date": snapshot.run_date,
                    "M": snapshot.proxy.M,
                    "D": snapshot.proxy.D,
                    "K": snapshot.proxy.K,
                    "X": snapshot.proxy.X,
                }
            )
        if not records:
            return pd.DataFrame(columns=["M", "D", "K", "X"])
        return pd.DataFrame.from_records(records).set_index("date")

    def _load_event_log(self) -> pd.DataFrame:
        if self.event_loader is None:
            return pd.DataFrame(columns=["date", "channel", "event"])
        try:
            loaded = self.event_loader()
        except Exception as exc:
            self._log_warning(f"event_loader failed: {exc}")
            return pd.DataFrame(columns=["date", "channel", "event"])
        if loaded is None:
            return pd.DataFrame(columns=["date", "channel", "event"])
        return loaded

    def _apply_structural_operators(self, proxy, event_log: pd.DataFrame, run_date: str):
        if self.operator_registry is None:
            return proxy, None
        operator_cfg = self.config.get("operators", {})
        if not isinstance(operator_cfg, dict):
            operator_cfg = {}
        singular_cfg = self.config.get("thresholds", {})
        if isinstance(singular_cfg, dict) and "sigma" in singular_cfg:
            operator_cfg = dict(operator_cfg)
            operator_cfg.setdefault("singular_threshold", singular_cfg.get("sigma"))

        # Mechanisms become prefix operators so they compose in the same algebra
        # as event shocks and appear in sequence diagnostics.
        mechanism_registry = getattr(self.ode_engine, "mechanism_registry", None)
        prefix_operators = mechanism_registry.as_operator_sequence() if mechanism_registry is not None else []

        try:
            return apply_event_log_to_proxy(
                proxy=proxy,
                event_log=event_log,
                registry=self.operator_registry,
                run_date=run_date,
                config=operator_cfg,
                prefix_operators=prefix_operators if prefix_operators else None,
            )
        except Exception as exc:
            self._log_warning(f"structural operator layer failed: {exc}")
            return proxy, None

    def _load_recent_texts(self, run_date: str) -> list[dict]:
        if self.recent_text_loader is None:
            return []
        try:
            loaded = self.recent_text_loader(run_date)
        except Exception as exc:
            self._log_warning(f"recent_text_loader failed: {exc}")
            return []
        if not loaded:
            return []
        return loaded

    def _log_warning(self, msg: str) -> None:
        logging.warning(msg)

    def _normalize_run_date(self, run_date: str) -> str:
        return pd.to_datetime(run_date).strftime("%Y-%m-%d")

    def _ode_params(self) -> dict[str, Any]:
        params = self.config.get("ode_params", {})
        params = dict(params) if isinstance(params, dict) else {}
        # Mechanisms now run as prefix operators; tell ODE not to apply them again.
        params["skip_mechanism_shift"] = True
        return params
