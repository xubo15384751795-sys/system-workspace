from __future__ import annotations

from datetime import date
from typing import Any

import yaml
from pydantic import ValidationError

from src.api.dto import (
    DateRangeQuery,
    EventRequest,
    EvidenceRouteRequest,
    FilingRequest,
    PositionRequest,
    SeriesRequest,
    SnapshotRunRequest,
    StructuralPresetRequest,
    request_payload,
)
from src.api.security import (
    install_api_key_middleware,
    resolve_api_key,
    resolve_harvester_validation,
)
from src.runtime.assembly import create_system_api
from src.runtime.system_api import StructuralSystemAPI


def create_service(config: dict[str, Any], use_mock: bool = True) -> StructuralSystemAPI:
    return create_system_api(config=config, use_mock=use_mock)


def create_app(
    config_path: str = "config.yaml",
    use_mock: bool = True,
    *,
    api_key: str | None = None,
):
    try:
        from fastapi import Body, Depends, FastAPI, HTTPException, Query
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install fastapi and uvicorn to run the terminal API.") from exc

    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    service = create_service(config=config, use_mock=use_mock)
    app = FastAPI(title="Structural Deformation Terminal API", version="0.1.0")
    resolved_api_key = api_key if api_key is not None else resolve_api_key(config)
    install_api_key_middleware(app, api_key=resolved_api_key)

    def date_range_query(
        start: date = Query(date(2026, 1, 1)),
        end: date = Query(date(2026, 4, 20)),
    ) -> DateRangeQuery:
        """Parse bounded query dates and expose model errors as HTTP 422."""
        try:
            return DateRangeQuery(start=start, end=end)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="invalid date range") from exc

    @app.get("/health")
    def health():
        return service.health()

    @app.get("/runtime")
    def runtime():
        return service.runtime()

    @app.get("/series")
    def series():
        return {"series": service.available_series()}

    @app.get("/data")
    def data(
        series_ids: list[str] = Query(..., min_length=1, max_length=64),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        return service.fetch_data(
            series_ids=series_ids,
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )

    @app.post("/snapshots/run")
    def run_snapshot(request: SnapshotRunRequest = Body(...)):
        return service.run_snapshot(run_date=request.run_date, run_type=request.run_type)

    @app.get("/snapshots")
    def snapshots(date_range: DateRangeQuery = Depends(date_range_query)):
        return {
            "snapshots": service.list_snapshots(
                start=date_range.start.isoformat(),
                end=date_range.end.isoformat(),
            )
        }

    @app.get("/snapshots/{run_date}")
    def snapshot(run_date: str):
        payload = service.get_snapshot(run_date)
        if payload is None:
            raise HTTPException(status_code=404, detail="snapshot not found")
        return payload

    @app.get("/hub/providers")
    def hub_providers():
        return service.available_data_providers()

    @app.get("/hub/presets")
    def hub_presets():
        return {"presets": service.available_structural_presets()}

    @app.get("/hub/capabilities")
    def hub_capabilities():
        return {"capabilities": service.provider_capabilities()}

    @app.post("/hub/route")
    def hub_route(request: EvidenceRouteRequest = Body(...)):
        return service.route_evidence(request_payload(request))

    @app.post("/hub/structural")
    def hub_structural(
        request: StructuralPresetRequest = Body(...),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        return service.fetch_structural_presets(
            preset_names=request.preset_names,
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )

    @app.post("/hub/series")
    def hub_series(
        requests: list[SeriesRequest] = Body(..., min_length=1, max_length=64),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        return service.fetch_series(
            requests=[request_payload(request) for request in requests],
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )

    @app.post("/hub/events")
    def hub_events(
        requests: list[EventRequest] = Body(..., min_length=1, max_length=64),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        return service.fetch_events(
            requests=[request_payload(request) for request in requests],
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )

    @app.post("/hub/filings")
    def hub_filings(
        requests: list[FilingRequest] = Body(..., min_length=1, max_length=64),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        return service.fetch_filings(
            requests=[request_payload(request) for request in requests],
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )

    @app.post("/hub/positions")
    def hub_positions(
        requests: list[PositionRequest] = Body(..., min_length=1, max_length=64),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        return service.fetch_positions(
            requests=[request_payload(request) for request in requests],
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )

    # ------------------------------------------------------------------
    # D.3: /hub_lite shadow endpoints — Harvester-backed DataHubLite
    # ------------------------------------------------------------------

    _lite = _build_lite_service(config)

    @app.get("/hub_lite/capabilities")
    def hub_lite_capabilities():
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        return {"capabilities": _lite.provider_capabilities()}

    @app.get("/hub_lite/presets")
    def hub_lite_presets():
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        return {"presets": _lite.available_structural_presets()}

    @app.get("/hub_lite/providers")
    def hub_lite_providers():
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        return _lite.available_providers()

    @app.post("/hub_lite/series")
    def hub_lite_series(
        requests: list[SeriesRequest] = Body(..., min_length=1, max_length=64),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        result = _lite.fetch_series(
            [request_payload(request) for request in requests],
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )
        return result.to_dict()

    @app.post("/hub_lite/structural")
    def hub_lite_structural(
        request: StructuralPresetRequest = Body(...),
        date_range: DateRangeQuery = Depends(date_range_query),
    ):
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        result = _lite.fetch_structural_presets(
            request.preset_names,
            start=date_range.start.isoformat(),
            end=date_range.end.isoformat(),
        )
        return result.to_dict()

    @app.get("/hub_lite/health")
    def hub_lite_health():
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        from src.data_access.health_report import build_health_report
        report = build_health_report(
            _lite,
            backend="harvester",
            release_id=_lite.release_id,
            network_calls=0,
        )
        return {
            "backend": report.current_backend,
            "release_id": report.current_release_id,
            "series_coverage": report.series_coverage,
            "missing_series": report.missing_series,
            "retired_series": report.retired_series,
            "warnings": report.warnings,
        }

    return app


def _build_lite_service(config: dict[str, Any]) -> Any | None:
    """Build a DataHubLite instance from config for /hub_lite shadow endpoints."""
    try:
        from pathlib import Path

        from src.data.gateway.data_hub_lite import DataHubLite
        from src.data.paths import default_harvester_contract_root
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
            contract_root = str(default_harvester_contract_root(config))

        validate_hashes, validate_schema = resolve_harvester_validation(config)
        adapter = HarvesterAdapter(
            exports_root=Path(exports_root),
            release=str(hcfg.get("release", "latest")),
            contract_root=contract_root,
            require_finalized=True,
            validate_hashes=validate_hashes,
            validate_schema=validate_schema,
        )
        return DataHubLite(adapter=adapter)
    except Exception:
        return None
