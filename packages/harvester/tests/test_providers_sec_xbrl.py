from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pandas as pd

from harvester.providers.sec import (
    DEALER_BANK_CIKS,
    OBS_SERIES_ID,
    SecProvider,
)


def _concept(tag: str, rows: list[dict]) -> dict:
    return {
        "cik": 0,
        "taxonomy": "us-gaap",
        "tag": tag,
        "units": {"USD": rows},
    }


def _mock_response(json_data: dict, status: int = 200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status
    resp.content = json.dumps(json_data).encode("utf-8")
    resp.raise_for_status = MagicMock()
    if status >= 400:
        from requests.exceptions import HTTPError

        resp.raise_for_status.side_effect = HTTPError(response=resp)
    return resp


def _build_provider(side_effect, tmp_path) -> SecProvider:
    with patch("requests.Session") as mock_session_cls, \
         patch("harvester.providers.sec.time.sleep"):
        mock_session = MagicMock()
        mock_session.headers = {}
        mock_session.get.side_effect = side_effect
        mock_session_cls.return_value = mock_session
        prov = SecProvider(data_root=str(tmp_path), cache=False)
        # keep the patched session through the call
        prov._session = mock_session
        return prov


class TestSecXbrlObs:
    def test_aggregate_ratio(self, tmp_path) -> None:
        # Every bank reports Assets=100 and DerivativeNotionalAmount=300 for
        # 2023-Q1 -> ratio = (n*300)/(n*100) = 3.0.
        assets = _concept("Assets", [
            {"end": "2023-03-31", "val": 100.0, "filed": "2023-05-01", "frame": "CY2023Q1I"},
        ])
        notional = _concept("DerivativeNotionalAmount", [
            {"end": "2023-03-31", "val": 300.0, "filed": "2023-05-01", "frame": "CY2023Q1I"},
        ])

        def side_effect(url, **kwargs):
            if url.endswith("/us-gaap/Assets.json"):
                return _mock_response(assets)
            if url.endswith("/us-gaap/DerivativeNotionalAmount.json"):
                return _mock_response(notional)
            return _mock_response({}, status=404)

        prov = _build_provider(side_effect, tmp_path)
        results = prov.fetch_series([OBS_SERIES_ID])

        assert len(results) == 1
        r = results[0]
        assert r.fetch_error is None
        assert r.series_id == OBS_SERIES_ID
        df = r.frame
        assert not df.empty
        assert df["unit"].iloc[0] == "ratio"
        assert df["frequency"].iloc[0] == "quarterly"
        row = df[df["date"] == pd.Timestamp("2023-03-31")]
        assert len(row) == 1
        assert abs(row["value"].iloc[0] - 3.0) < 1e-9
        # all six banks contributed
        assert len(r.source_params["basket"].split(",")) == len(DEALER_BANK_CIKS)

    def test_fallback_numerator_tag(self, tmp_path) -> None:
        # Primary numerator tag 404s; secondary tag carries the data.
        assets = _concept("Assets", [
            {"end": "2022-12-31", "val": 200.0, "filed": "2023-02-01"},
        ])
        notional = _concept("NotionalAmountOfDerivatives", [
            {"end": "2022-12-31", "val": 100.0, "filed": "2023-02-01"},
        ])

        def side_effect(url, **kwargs):
            if url.endswith("/us-gaap/Assets.json"):
                return _mock_response(assets)
            if url.endswith("/us-gaap/NotionalAmountOfDerivatives.json"):
                return _mock_response(notional)
            return _mock_response({}, status=404)  # DerivativeNotionalAmount missing

        prov = _build_provider(side_effect, tmp_path)
        r = prov.fetch_series([OBS_SERIES_ID])[0]
        assert r.fetch_error is None
        row = r.frame[r.frame["date"] == pd.Timestamp("2022-12-31")]
        assert abs(row["value"].iloc[0] - 0.5) < 1e-9

    def test_latest_filed_wins_per_period(self, tmp_path) -> None:
        # Two facts for the same period-end: a restatement filed later must win.
        assets = _concept("Assets", [
            {"end": "2023-03-31", "val": 100.0, "filed": "2023-05-01"},
        ])
        notional = _concept("DerivativeNotionalAmount", [
            {"end": "2023-03-31", "val": 300.0, "filed": "2023-05-01"},
            {"end": "2023-03-31", "val": 900.0, "filed": "2023-08-01"},  # restated, later
        ])

        def side_effect(url, **kwargs):
            if url.endswith("/us-gaap/Assets.json"):
                return _mock_response(assets)
            if url.endswith("/us-gaap/DerivativeNotionalAmount.json"):
                return _mock_response(notional)
            return _mock_response({}, status=404)

        prov = _build_provider(side_effect, tmp_path)
        r = prov.fetch_series([OBS_SERIES_ID])[0]
        # restated notional 900 wins -> 900/100 = 9.0
        row = r.frame[r.frame["date"] == pd.Timestamp("2023-03-31")]
        assert abs(row["value"].iloc[0] - 9.0) < 1e-9

    def test_empty_when_no_numerator(self, tmp_path) -> None:
        assets = _concept("Assets", [
            {"end": "2023-03-31", "val": 100.0, "filed": "2023-05-01"},
        ])

        def side_effect(url, **kwargs):
            if url.endswith("/us-gaap/Assets.json"):
                return _mock_response(assets)
            return _mock_response({}, status=404)  # no notional tags at all

        prov = _build_provider(side_effect, tmp_path)
        r = prov.fetch_series([OBS_SERIES_ID])[0]
        assert r.fetch_error is not None
        assert r.frame.empty

    def test_dispatch_does_not_hit_filing_pulse(self, tmp_path) -> None:
        # OBS_SERIES_ID must route to the XBRL path (companyconcept URLs),
        # never the submissions/filing-pulse endpoint.
        seen: list[str] = []

        def side_effect(url, **kwargs):
            seen.append(url)
            if url.endswith("/us-gaap/Assets.json"):
                return _mock_response(_concept("Assets", [
                    {"end": "2023-03-31", "val": 100.0, "filed": "2023-05-01"}]))
            if url.endswith("/us-gaap/DerivativeNotionalAmount.json"):
                return _mock_response(_concept("DerivativeNotionalAmount", [
                    {"end": "2023-03-31", "val": 300.0, "filed": "2023-05-01"}]))
            return _mock_response({}, status=404)

        prov = _build_provider(side_effect, tmp_path)
        prov.fetch_series([OBS_SERIES_ID])
        assert seen, "no requests issued"
        assert all("/api/xbrl/companyconcept/" in u for u in seen)
        assert not any("/submissions/" in u for u in seen)

    def test_to_long_panel_namespaces_series(self, tmp_path) -> None:
        def side_effect(url, **kwargs):
            if url.endswith("/us-gaap/Assets.json"):
                return _mock_response(_concept("Assets", [
                    {"end": "2023-03-31", "val": 100.0, "filed": "2023-05-01"}]))
            if url.endswith("/us-gaap/DerivativeNotionalAmount.json"):
                return _mock_response(_concept("DerivativeNotionalAmount", [
                    {"end": "2023-03-31", "val": 300.0, "filed": "2023-05-01"}]))
            return _mock_response({}, status=404)

        prov = _build_provider(side_effect, tmp_path)
        results = prov.fetch_series([OBS_SERIES_ID])
        panel = prov._to_long_panel(results)
        assert not panel.empty
        assert panel["series_id"].iloc[0] == f"SEC:{OBS_SERIES_ID}"
        assert panel["source_id"].iloc[0] == "sec"
