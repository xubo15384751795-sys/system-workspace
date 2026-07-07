from __future__ import annotations

import logging
import time
from typing import Any

import pandas as pd
import requests

from harvester.providers.base import OfficialProvider, ProviderResult

logger = logging.getLogger(__name__)

SEC_SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
SEC_XBRL_CONCEPT_BASE = "https://data.sec.gov/api/xbrl/companyconcept"

SEC_HEADERS = {
    "User-Agent": "StructuralRiskHarvester/0.1.0 (contact@example.com)",
    "Accept-Encoding": "gzip, deflate",
    "Host": "data.sec.gov",
}

# ---------------------------------------------------------------------------
# X_agg v1 off-balance-sheet — SEC XBRL aggregate (Phase 1 interim).
# See governance/x_agg_v1_obs_procurement_plan.md. This is a derivatives-
# notional / total-assets ratio over a fixed basket of large dealer banks.
# It is a deliberately coarse interim proxy (XBRL derivative tagging is
# sparse/inconsistent across filers); the canonical source is FFIEC FR Y-9C
# Schedule HC-L (Phase 2). Marked here as a separate routed series id so the
# downstream Deformation proxy stays candidate_pending_promotion, not voting.
# ---------------------------------------------------------------------------
OBS_SERIES_ID = "OBS_DERIV_TO_ASSETS"

# SEC CIKs (not RSSD) for the large US dealer-bank basket.
DEALER_BANK_CIKS: dict[str, str] = {
    "JPM": "0000019617",
    "BAC": "0000070858",
    "C": "0000831001",
    "GS": "0000886982",
    "MS": "0000895421",
    "WFC": "0000072971",
}

# us-gaap numerator tags tried in priority order (first with data per CIK wins).
OBS_NUMERATOR_TAGS: tuple[str, ...] = (
    "DerivativeNotionalAmount",
    "NotionalAmountOfDerivatives",
)
OBS_DENOMINATOR_TAG = "Assets"


class SecProvider(OfficialProvider):
    source_id = "sec"

    def __init__(
        self,
        user_agent: str = "",
        data_root: str = "",
        cache: bool = True,
    ) -> None:
        ua = user_agent or SEC_HEADERS["User-Agent"]
        super().__init__(data_root=data_root, cache=cache, user_agent=ua)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": ua, "Accept-Encoding": "gzip, deflate"})

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        results: list[ProviderResult] = []
        for sid in series_ids:
            # Internal dispatch: the SEC provider serves two distinct shapes.
            # OBS_SERIES_ID is an XBRL-derived aggregate ratio; everything else
            # is treated as a CIK for the daily EDGAR filing-pulse count.
            if sid == OBS_SERIES_ID:
                result = self._fetch_obs_to_assets(sid)
            else:
                cik = self._normalize_cik(sid)
                result = self._fetch_filing_pulse(cik, sid)
            results.append(result)
            if sid != series_ids[-1]:
                time.sleep(0.5)  # SEC rate limit
        return results

    def _normalize_cik(self, raw: str) -> str:
        cik = raw.strip()
        return cik.lstrip("0") or "0"

    def _fetch_filing_pulse(self, cik: str, original_id: str) -> ProviderResult:
        padded = cik.zfill(10)
        url = f"{SEC_SUBMISSIONS_BASE}/CIK{padded}.json"

        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response else "?"
            if exc.response is not None and exc.response.status_code == 404:
                return self._build_error_result(
                    original_id, f"SEC CIK {cik} not found", "not_found"
                )
            msg = f"SEC HTTP {status} for CIK {cik}"
            logger.warning(msg)
            return self._build_error_result(original_id, msg, "http_error")
        except requests.exceptions.RequestException as exc:
            msg = f"SEC network error for CIK {cik}: {exc}"
            logger.warning(msg)
            return self._build_error_result(original_id, msg, "network_error")

        if self._cache:
            self._write_raw(f"cik_{padded}", raw_bytes)

        filings = data.get("filings", {}).get("recent", {})
        filing_dates = filings.get("filingDate", [])
        forms = filings.get("form", [])

        if not filing_dates:
            return self._build_error_result(original_id, "no filing dates returned", "empty")

        date_counts: dict[str, int] = {}
        for i, fd in enumerate(filing_dates):
            if not fd:
                continue
            date_counts[fd] = date_counts.get(fd, 0) + 1

        rows: list[dict[str, Any]] = []
        for dt, count in sorted(date_counts.items()):
            rows.append({
                "date": dt,
                "value": float(count),
                "unit": "filing_count",
                "frequency": "daily",
            })

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])

        return ProviderResult(
            provider=self.source_id,
            series_id=original_id,
            frame=df,
            source_url=url,
            source_params={"cik": padded},
        )

    # ------------------------------------------------------------------
    # X_agg v1 — XBRL companyconcept aggregate (derivatives notional / assets)
    # ------------------------------------------------------------------
    def _fetch_companyconcept(self, cik: str, tag: str) -> dict[pd.Period, float] | None:
        """Fetch a us-gaap concept time series for one CIK.

        Returns a {fiscal-quarter Period -> value} map, keeping the most
        recently filed observation per period-end. Returns None on any
        not-found / network / empty condition (caller skips that CIK/tag).
        """
        padded = cik.zfill(10)
        url = f"{SEC_XBRL_CONCEPT_BASE}/CIK{padded}/us-gaap/{tag}.json"
        try:
            resp = self._session.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            raw_bytes = resp.content
        except requests.exceptions.RequestException:
            return None

        if self._cache:
            self._write_raw(f"xbrl_{padded}_{tag}", raw_bytes)

        usd = data.get("units", {}).get("USD", [])
        if not usd:
            return None

        # Keep the latest-filed value per fiscal period-end.
        by_period: dict[pd.Period, tuple[str, float]] = {}
        for fact in usd:
            end = fact.get("end")
            val = fact.get("val")
            if end is None or val is None:
                continue
            try:
                period = pd.Timestamp(end).to_period("Q")
            except (ValueError, TypeError):
                continue
            filed = str(fact.get("filed", ""))
            prev = by_period.get(period)
            if prev is None or filed >= prev[0]:
                by_period[period] = (filed, float(val))
        if not by_period:
            return None
        return {p: v for p, (_, v) in by_period.items()}

    def _fetch_obs_to_assets(self, original_id: str) -> ProviderResult:
        """Aggregate derivatives-notional / total-assets over the dealer-bank basket.

        For each CIK we take the first numerator tag that returns data and the
        Assets denominator, then per fiscal quarter sum numerator and assets
        across only the banks that reported both, and emit the ratio.
        """
        num_by_period: dict[pd.Period, float] = {}
        den_by_period: dict[pd.Period, float] = {}
        contributing: list[str] = []

        ciks = list(DEALER_BANK_CIKS.items())
        for i, (label, cik) in enumerate(ciks):
            assets = self._fetch_companyconcept(cik, OBS_DENOMINATOR_TAG)
            if not assets:
                continue
            notional: dict[pd.Period, float] | None = None
            for tag in OBS_NUMERATOR_TAGS:
                notional = self._fetch_companyconcept(cik, tag)
                if notional:
                    break
            if not notional:
                continue
            shared = set(assets) & set(notional)
            if not shared:
                continue
            contributing.append(label)
            for period in shared:
                num_by_period[period] = num_by_period.get(period, 0.0) + notional[period]
                den_by_period[period] = den_by_period.get(period, 0.0) + assets[period]
            if i != len(ciks) - 1:
                time.sleep(0.5)  # SEC rate limit between issuers

        if not num_by_period:
            return self._build_error_result(
                original_id,
                "no XBRL derivatives-notional/assets data for dealer-bank basket",
                "empty",
            )

        rows: list[dict[str, Any]] = []
        for period in sorted(num_by_period):
            den = den_by_period.get(period, 0.0)
            if den <= 0:
                continue
            rows.append({
                "date": period.to_timestamp(how="end").normalize(),
                "value": num_by_period[period] / den,
                "unit": "ratio",
                "frequency": "quarterly",
            })
        if not rows:
            return self._build_error_result(
                original_id, "no quarters with positive total assets", "empty"
            )

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])

        return ProviderResult(
            provider=self.source_id,
            series_id=original_id,
            frame=df,
            source_url=f"{SEC_XBRL_CONCEPT_BASE}/CIK*/us-gaap/{{{','.join(OBS_NUMERATOR_TAGS)},{OBS_DENOMINATOR_TAG}}}.json",
            source_params={"basket": ",".join(contributing)},
            data_note=(
                "Phase 1 interim OBS proxy: aggregate derivatives-notional/assets "
                f"over {len(contributing)} dealer banks ({', '.join(contributing)}). "
                "Coarse — canonical source is FFIEC FR Y-9C Schedule HC-L."
            ),
        )
