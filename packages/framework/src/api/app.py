from __future__ import annotations

from typing import Any

import yaml

from src.api.security import install_api_key_middleware, resolve_api_key, resolve_harvester_validation
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
        from fastapi import Body, FastAPI, HTTPException, Query
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("Install fastapi and uvicorn to run the terminal API.") from exc

    with open(config_path, "r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    service = create_service(config=config, use_mock=use_mock)
    app = FastAPI(title="Structural Deformation Terminal API", version="0.1.0")
    resolved_api_key = api_key if api_key is not None else resolve_api_key(config)
    install_api_key_middleware(app, api_key=resolved_api_key)

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
        series_ids: list[str] = Query(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        return service.fetch_data(series_ids=series_ids, start=start, end=end)

    @app.post("/snapshots/run")
    def run_snapshot(run_date: str, run_type: str = "WEEKLY"):
        return service.run_snapshot(run_date=run_date, run_type=run_type)

    @app.get("/snapshots")
    def snapshots(start: str = "1900-01-01", end: str = "2999-12-31"):
        return {"snapshots": service.list_snapshots(start=start, end=end)}

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
    def hub_route(request: dict[str, Any] = Body(...)):
        return service.route_evidence(request)

    @app.post("/hub/structural")
    def hub_structural(
        preset_names: list[str] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        return service.fetch_structural_presets(preset_names=preset_names, start=start, end=end)

    @app.post("/hub/series")
    def hub_series(
        requests: list[dict[str, Any]] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        return service.fetch_series(requests=requests, start=start, end=end)

    @app.post("/hub/events")
    def hub_events(
        requests: list[dict[str, Any]] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        return service.fetch_events(requests=requests, start=start, end=end)

    @app.post("/hub/filings")
    def hub_filings(
        requests: list[dict[str, Any]] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        return service.fetch_filings(requests=requests, start=start, end=end)

    @app.post("/hub/positions")
    def hub_positions(
        requests: list[dict[str, Any]] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        return service.fetch_positions(requests=requests, start=start, end=end)

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
        requests: list[dict[str, Any]] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        result = _lite.fetch_series(requests, start=start, end=end)
        return result.to_dict()

    @app.post("/hub_lite/structural")
    def hub_lite_structural(
        preset_names: list[str] = Body(...),
        start: str = "2026-01-01",
        end: str = "2026-04-20",
    ):
        if _lite is None:
            raise HTTPException(status_code=503, detail="Harvester backend not configured")
        result = _lite.fetch_structural_presets(preset_names, start=start, end=end)
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
        from src.data_access.harvester_adapter import HarvesterAdapter
        from src.data.gateway.data_hub_lite import DataHubLite

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
