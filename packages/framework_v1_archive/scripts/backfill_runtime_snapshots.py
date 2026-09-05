from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_ROOT = ROOT.parent

from src.core.execution import RunContext
from src.runtime.assembly import build_system
from src.data.paths import resolve_fred_cache_dir, resolve_snapshot_store_path


DEFAULT_START = "2015-01-05"
DEFAULT_END = "2026-04-22"
DEFAULT_FREQ = "W-MON"
FRED_SERIES_FOR_PROXY = ("T10Y2Y", "DFF", "TEDRATE", "BAMLH0A0HYM2", "VIXCLS")


@dataclass(frozen=True)
class BackfillResult:
    processed: int
    created_or_reused: int
    failed: int
    elapsed_sec: float


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return config


def _date_range(start: str, end: str, freq: str) -> list[str]:
    dates = pd.date_range(start=start, end=end, freq=freq)
    return [item.strftime("%Y-%m-%d") for item in dates]


def _fred_raw_dir() -> Path:
    return SYSTEM_ROOT / "Data" / "harvester" / "raw" / "fred"


def _hydrate_fred_cache(config: dict[str, Any], series_ids: tuple[str, ...]) -> list[Path]:
    """Convert Harvester FRED raw JSON into the graph CSV cache format.

    The legacy FRED adapter reads `<series_id>.csv` with columns
    `observation_date,<series_id>`. Harvester already has richer raw JSON on
    disk, so this keeps backfills offline while using the existing adapter path.
    """
    cache_dir = resolve_fred_cache_dir(config)
    raw_dir = _fred_raw_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for series_id in series_ids:
        csv_path = cache_dir / f"{series_id}.csv"
        raw_json_path = raw_dir / f"{series_id}_raw.json"
        raw_csv_path = raw_dir / f"{series_id}.csv"

        if raw_json_path.exists():
            payload = json.loads(raw_json_path.read_text(encoding="utf-8"))
            observations = payload.get("observations", []) if isinstance(payload, dict) else []
            rows: list[dict[str, Any]] = []
            for obs in observations:
                if not isinstance(obs, dict):
                    continue
                value = obs.get("value")
                if value in (None, "", "."):
                    continue
                rows.append({"observation_date": obs.get("date"), series_id: value})
            frame = pd.DataFrame(rows)
        elif raw_csv_path.exists():
            frame = pd.read_csv(raw_csv_path)
            if "observation_date" not in frame.columns:
                first = frame.columns[0]
                frame = frame.rename(columns={first: "observation_date"})
            value_cols = [col for col in frame.columns if col != "observation_date"]
            if series_id not in frame.columns and value_cols:
                frame = frame.rename(columns={value_cols[0]: series_id})
            frame = frame[["observation_date", series_id]]
        else:
            raise FileNotFoundError(f"Missing Harvester FRED raw file for {series_id}: {raw_json_path}")

        frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
        frame[series_id] = pd.to_numeric(frame[series_id], errors="coerce")
        frame = frame.dropna(subset=["observation_date", series_id]).sort_values("observation_date")
        frame["observation_date"] = frame["observation_date"].dt.strftime("%Y-%m-%d")
        frame.to_csv(csv_path, index=False)
        written.append(csv_path)

    return written


def _prepare_config(config: dict[str, Any], history_start: str, offline: bool) -> dict[str, Any]:
    prepared = copy.deepcopy(config)
    prepared["history_start"] = history_start
    prepared.setdefault("pipeline", {})["reuse_existing_snapshot"] = True

    if offline:
        data_sources = prepared.setdefault("data_sources", {})
        # Keep non-FRED providers on deterministic fallback paths instead of
        # reaching remote endpoints during a runtime history rebuild.
        data_sources["sec_user_agent"] = ""
        data_sources["treasury_base_url"] = ""
        data_sources["h41_csv_url"] = ""

    return prepared


def run_backfill(
    *,
    config_path: Path,
    start: str,
    end: str,
    freq: str,
    run_type: str,
    limit: int | None,
    dry_run: bool,
    hydrate_fred_cache: bool,
    offline: bool,
) -> BackfillResult:
    config = _prepare_config(_load_config(config_path), history_start=start, offline=offline)
    dates = _date_range(start, end, freq)
    if limit is not None:
        dates = dates[: max(0, limit)]

    if hydrate_fred_cache:
        written = _hydrate_fred_cache(config, FRED_SERIES_FOR_PROXY)
        print(f"Hydrated FRED cache files: {len(written)} -> {resolve_fred_cache_dir(config)}")

    snapshot_path = resolve_snapshot_store_path(config)
    print(f"Snapshot store: {snapshot_path}")
    print(f"Backfill window: {start} -> {end} ({len(dates)} dates, {freq})")

    if dry_run:
        for date in dates:
            print(date)
        return BackfillResult(processed=0, created_or_reused=0, failed=0, elapsed_sec=0.0)

    pipeline = build_system(config, use_mock=False)
    started = perf_counter()
    failed = 0

    for idx, run_date in enumerate(dates, start=1):
        try:
            ctx = RunContext.from_config(config=config, run_date=run_date, run_type=run_type)
            snapshot = pipeline.run(ctx)
            status = "escalated" if snapshot.escalation else "ok"
            print(f"[{idx:04d}/{len(dates):04d}] {run_date} {status}")
        except Exception as exc:
            failed += 1
            print(f"[{idx:04d}/{len(dates):04d}] {run_date} failed: {exc}")

    elapsed = perf_counter() - started
    processed = len(dates)
    return BackfillResult(
        processed=processed,
        created_or_reused=processed - failed,
        failed=failed,
        elapsed_sec=elapsed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill runtime DuckDB snapshots by replaying ResearchPipeline.run() over historical dates."
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--freq", default=DEFAULT_FREQ)
    parser.add_argument("--run-type", default="WEEKLY")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-hydrate-fred-cache", action="store_true")
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Allow configured non-FRED public endpoints instead of forcing local/fallback-only mode.",
    )
    args = parser.parse_args()

    result = run_backfill(
        config_path=args.config,
        start=args.start,
        end=args.end,
        freq=args.freq,
        run_type=args.run_type,
        limit=args.limit,
        dry_run=args.dry_run,
        hydrate_fred_cache=not args.no_hydrate_fred_cache,
        offline=not args.allow_remote,
    )
    print(
        "Backfill complete: "
        f"processed={result.processed}, "
        f"created_or_reused={result.created_or_reused}, "
        f"failed={result.failed}, "
        f"elapsed_sec={result.elapsed_sec:.1f}"
    )


if __name__ == "__main__":
    main()
