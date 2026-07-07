from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field as dc_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


OFFICIAL_PANEL_COLUMNS = [
    "date",
    "series_id",
    "source_id",
    "source_series_id",
    "value",
    "unit",
    "frequency",
    "vintage_date",
    "quality_flag",
]


@dataclass
class ProviderResult:
    provider: str
    series_id: str
    frame: pd.DataFrame
    fetch_error: str | None = None
    fetch_fallback_reason: str | None = None
    data_note: str | None = None
    source_url: str = ""
    source_params: dict[str, Any] = dc_field(default_factory=dict)

    def empty(self) -> bool:
        return self.frame is None or (isinstance(self.frame, pd.DataFrame) and self.frame.empty)

    def row_count(self) -> int:
        if self.empty():
            return 0
        return len(self.frame)


class OfficialProvider:
    source_id: str = ""

    def __init__(
        self,
        data_root: str | Path = "",
        cache: bool = True,
        user_agent: str = "StructuralRiskHarvester/0.1.0",
    ) -> None:
        self._data_root = Path(data_root) if data_root else self._default_data_root()
        self._cache = cache
        self._user_agent = user_agent

    def fetch_series(self, series_ids: list[str]) -> list[ProviderResult]:
        raise NotImplementedError

    @staticmethod
    def _default_data_root() -> Path:
        return Path(__file__).resolve().parents[3] / "data"

    def _raw_dir(self) -> Path:
        return self._data_root / "raw" / self.source_id

    def _write_raw(self, key: str, content: bytes | str) -> Path:
        p = self._raw_dir()
        p.mkdir(parents=True, exist_ok=True)
        path = p / f"{key}_raw.json"
        data = content.decode("utf-8") if isinstance(content, bytes) else content
        path.write_text(data, encoding="utf-8")
        return path

    def _read_raw(self, key: str) -> bytes | None:
        path = self._raw_dir() / f"{key}_raw.json"
        if path.exists():
            return path.read_bytes()
        return None

    def _raw_sha256(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def _build_error_result(self, series_id: str, error: str, reason: str = "") -> ProviderResult:
        return ProviderResult(
            provider=self.source_id,
            series_id=series_id,
            frame=pd.DataFrame(),
            fetch_error=error,
            fetch_fallback_reason=reason,
        )

    def _to_long_panel(self, results: list[ProviderResult]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for r in results:
            if r.empty():
                continue
            df = r.frame.copy()
            df["series_id"] = f"{self.source_id.upper()}:{r.series_id}"
            df["source_id"] = self.source_id
            df["source_series_id"] = r.series_id
            if "unit" not in df.columns:
                df["unit"] = ""
            if "frequency" not in df.columns:
                df["frequency"] = ""
            if "vintage_date" not in df.columns:
                df["vintage_date"] = datetime.now(UTC).strftime("%Y-%m-%d")
            if "quality_flag" not in df.columns:
                qf = 0
                if r.fetch_error or r.fetch_fallback_reason:
                    qf = 2
                elif r.fetch_fallback_reason:
                    qf = 1
                df["quality_flag"] = qf
            frames.append(df[
                [c for c in OFFICIAL_PANEL_COLUMNS if c in df.columns]
            ])
        if not frames:
            return pd.DataFrame(columns=OFFICIAL_PANEL_COLUMNS)
        return pd.concat(frames, ignore_index=True)
