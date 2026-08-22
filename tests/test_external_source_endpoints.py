from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pandas as pd
from harvester.http_gateway import GatewayResponse

from scripts.check_external_source_endpoints import probe_external_sources


def _xlsx_bytes() -> bytes:
    stream = BytesIO()
    pd.DataFrame(
        {
            "Year-Month": ["2026-07"],
            "Debit Balances in Customers' Securities Margin Accounts": [1417225],
        }
    ).to_excel(stream, index=False)
    return stream.getvalue()


def _zip_bytes() -> bytes:
    stream = BytesIO()
    with ZipFile(stream, "w") as archive:
        archive.writestr("CoVaR_qtrly.dta", b"fixture")
        archive.writestr("CoVaRqtrly.csv", b"metadata")
    return stream.getvalue()


def test_monthly_probe_separates_covar_transport_from_aggregation() -> None:
    responses = {
        ("nyfed", "COVAR"): GatewayResponse(200, {}, _zip_bytes()),
        ("finra", "FINRA_MARGIN_DEBT"): GatewayResponse(200, {}, _xlsx_bytes()),
    }

    class Gateway:
        def fetch(self, provider: str, endpoint_id: str, *_args, **_kwargs):
            return responses[(provider, endpoint_id)]

    report = probe_external_sources(gateway=Gateway())

    assert report["ok"] is True
    covar = next(row for row in report["results"] if row["indicator"] == "COVAR")
    finra = next(row for row in report["results"] if row["indicator"] == "FINRA_MARGIN_DEBT")
    assert covar["status"] == "transport_ok_manual_aggregate_pending"
    assert covar["semantic_status"] == "manual_aggregate_required"
    assert finra["status"] == "pass"
    assert finra["latest_date"] == "2026-07-01"
