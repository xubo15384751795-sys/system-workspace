from __future__ import annotations

# DEPRECATED: legacy data access remains for backward compatibility during the
# Harvester transition. Removal date: TBD by user.

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import pandas as pd

from src.data.paths import resolve_data_root


LEGACY_TABLE_PATHS: dict[str, tuple[str, ...]] = {
    "raw_series": ("raw/raw_series.parquet",),
    "proxy_readings": ("processed/proxies/proxy_readings.parquet",),
    "structural_state": ("processed/state/structural_state.parquet",),
    "snapshots": ("processed/snapshots/snapshots.parquet",),
    "event_log": ("processed/events/event_log.parquet",),
}


@dataclass(frozen=True)
class LegacyDataInventoryEntry:
    path: str
    file_type: str
    size_bytes: int
    source_role: str
    migration_target: str = "audit_before_migration"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "file_type": self.file_type,
            "size_bytes": self.size_bytes,
            "source_role": self.source_role,
            "migration_target": self.migration_target,
        }


class LegacyDataAdapter:
    """Read the current in-project data layout without mutating it."""

    backend = "legacy"

    def __init__(self, config: dict[str, Any] | None = None, *, data_root: Path | str | None = None) -> None:
        self.config = config or {}
        self.data_root = Path(data_root).expanduser() if data_root is not None else resolve_data_root(self.config)
        _reject_harvester_internal_root(self.data_root)

    def exists(self) -> bool:
        return self.data_root.exists()

    def inventory(self) -> list[LegacyDataInventoryEntry]:
        if not self.data_root.exists():
            return []
        entries: list[LegacyDataInventoryEntry] = []
        for path in sorted(self.data_root.rglob("*")):
            if not path.is_file():
                continue
            entries.append(
                LegacyDataInventoryEntry(
                    path=str(path),
                    file_type=_file_type(path),
                    size_bytes=path.stat().st_size,
                    source_role=_infer_source_role(path),
                )
            )
        return entries

    def load_table(self, name: str) -> pd.DataFrame:
        candidates = LEGACY_TABLE_PATHS.get(name)
        if not candidates:
            raise KeyError(f"unknown legacy table: {name}")
        for rel in candidates:
            path = self.data_root / rel
            if path.exists():
                frame = _read_table(path)
                return _ensure_source_role(frame, _infer_source_role(path))
        raise FileNotFoundError(f"legacy table {name!r} not found under {self.data_root}")

    def load_available_tables(self) -> dict[str, pd.DataFrame]:
        tables: dict[str, pd.DataFrame] = {}
        for name in LEGACY_TABLE_PATHS:
            try:
                tables[name] = self.load_table(name)
            except FileNotFoundError:
                continue
        return tables


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return _read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".json", ".jsonl"}:
        return _read_json_like(path)
    raise ValueError(f"unsupported legacy table file type: {path}")


def _read_parquet(path: Path) -> pd.DataFrame:
    try:
        return pd.read_parquet(path)
    except Exception:
        try:
            import polars as pl

            return pd.DataFrame(pl.read_parquet(path).to_dicts())
        except Exception as exc:
            raise RuntimeError(f"could not read parquet file {path}") from exc


def _read_json_like(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return pd.DataFrame(rows)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return pd.DataFrame(payload)
    if isinstance(payload, dict):
        return pd.DataFrame([payload])
    raise ValueError(f"unsupported json payload in {path}")


def _ensure_source_role(frame: pd.DataFrame, source_role: str) -> pd.DataFrame:
    if "source_role" in frame.columns:
        return frame
    out = frame.copy()
    out["source_role"] = source_role
    return out


def _file_type(path: Path) -> str:
    if path.suffix:
        return path.suffix.lower().lstrip(".")
    return "unknown"


def _infer_source_role(path: Path) -> str:
    normalized = "/".join(path.parts).casefold()
    if "benchmark" in normalized:
        return "benchmark"
    if "proxy" in normalized:
        return "proxy_candidate"
    if "research_corpus" in normalized or "corpus" in normalized:
        return "corpus"
    return "legacy"


def _reject_harvester_internal_root(path: Path) -> None:
    from src.core.runtime_context import RuntimePaths

    normalized = path.expanduser().resolve(strict=False).as_posix()
    harvester_root = RuntimePaths.discover().harvester_root.as_posix()
    forbidden = (
        f"{harvester_root}/raw",
        f"{harvester_root}/processed",
        f"{harvester_root}/corpus",
    )
    if any(normalized == item or normalized.startswith(f"{item}/") for item in forbidden):
        raise ValueError(f"legacy backend must not read Harvester internal data: {path}")


__all__ = ["LEGACY_TABLE_PATHS", "LegacyDataAdapter", "LegacyDataInventoryEntry"]
