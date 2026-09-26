"""Monthly endpoint probes for repaired external indicators.

This is intentionally a read-only source check.  It verifies that the fixed
publisher endpoint is reachable without redirects and that the response still
has the expected container/schema.  It does not silently turn the NY Fed's
firm-level CoVaR archive into an aggregate scalar.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from harvester.http_gateway import (
    GatewayResponse,
    OwnedHTTPGateway,
)
from harvester.providers.external_indicators import (
    COVAR,
    EXTERNAL_ENDPOINTS,
    EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES,
    FINRA_MARGIN_DEBT,
    _parse_finra_margin_debt,
)

ROOT = Path(__file__).resolve().parents[5]
REPORT_PATH = ROOT / "Data" / "system_index" / "external_source_endpoint_health.json"
MONITORING_POLICY_REL = "governance/external_source_monitoring.yaml"
MONTHLY_INDICATORS = (COVAR, FINRA_MARGIN_DEBT)


def _probe_indicator(indicator: Any, gateway: Any) -> dict[str, Any]:
    try:
        response: GatewayResponse = gateway.fetch(indicator.authority_id, indicator.name)
        response.raise_for_status()
        if indicator.name == "COVAR":
            with zipfile.ZipFile(BytesIO(response.content)) as archive:
                names = set(archive.namelist())
            required = {"CoVaR_qtrly.dta", "CoVaRqtrly.csv"}
            missing = sorted(required - names)
            if missing:
                raise ValueError(f"CoVaR archive missing files: {missing}")
            return {
                "indicator": indicator.name,
                "status": "transport_ok_manual_aggregate_pending",
                "ok": True,
                "semantic_status": "manual_aggregate_required",
                "archive_files": sorted(required),
                "bytes": len(response.content),
            }

        series = _parse_finra_margin_debt(response.content)
        if series.empty:
            raise ValueError("FINRA response parsed to zero observations")
        return {
            "indicator": indicator.name,
            "status": "pass",
            "ok": True,
            "rows": int(len(series)),
            "latest_date": str(series.index.max().date()),
        }
    except Exception as exc:  # noqa: BLE001 - probe must record the exact failure
        return {
            "indicator": indicator.name,
            "status": "fail",
            "ok": False,
            "error": str(exc)[:500],
        }


def probe_external_sources(*, gateway: Any | None = None) -> dict[str, Any]:
    owns_gateway = gateway is None
    client = gateway or OwnedHTTPGateway(
        endpoint_registry=EXTERNAL_ENDPOINTS,
        headers={"User-Agent": "StructuralRiskHarvester/0.1.0"},
        max_response_bytes=EXTERNAL_INDICATOR_MAX_RESPONSE_BYTES,
    )
    try:
        results = [_probe_indicator(indicator, client) for indicator in MONTHLY_INDICATORS]
    finally:
        if owns_gateway:
            client.close()
    return {
        "schema_version": "external_source_probe.v1",
        "cadence": "monthly",
        "checked_at": datetime.now(UTC).isoformat(),
        "results": results,
        "ok": all(bool(result.get("ok")) for result in results),
    }


def _write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print the probe report")
    parser.add_argument("--no-write", action="store_true", help="do not update the health report")
    args = parser.parse_args(argv)
    report = probe_external_sources()
    if not args.no_write:
        _write_report(report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
