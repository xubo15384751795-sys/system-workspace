"""One-time repair of the cross-asset workspace mirror.

This script is deterministic once its provider inputs exist. It takes the
newest clean Harvester release as a historical anchor, uses a full-history
provider snapshot when supplied, and overlays already downloaded Tiingo raw
OHLCV rows for the recent tail. It then rebuilds all derived columns and
validates the release contract before atomically replacing
``Data/panels/cross_asset_daily_panel.parquet``.

The repository currently declares 33 ETFs in ``configs/data/etf_universe.yaml``;
there is no local D1=A/24-symbol manifest.  The default therefore uses the
declared 33-symbol contract.  A caller with an explicit, reviewed symbol list
can pass ``--symbols``; this does not weaken the contract for the default
workspace universe.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import pandas as pd
from harvester.cross_asset_panel import (
    PANEL_COLUMNS,
    compute_derived_columns,
    resolve_etf_universe,
)
from harvester.quality.data_contract import validate_cross_asset_panel_contract

RAW_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume"]
NUMERIC_COLUMNS = ["open", "high", "low", "close", "volume"]
DEFAULT_OUTPUT = Path("Data/panels/cross_asset_daily_panel.parquet")
DEFAULT_PROVIDER_CACHE = Path("Data/harvester/raw/tiingo")


def _parse_symbols(value: str | None, configured: list[str]) -> list[str]:
    if not value:
        return configured
    requested = sorted({item.strip().upper() for item in value.split(",") if item.strip()})
    unknown = sorted(set(requested) - set(configured))
    if unknown:
        raise ValueError(f"symbols not in configured ETF universe: {','.join(unknown)}")
    if not requested:
        raise ValueError("--symbols must contain at least one ticker")
    return requested


def _normalise_ohlcv(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if "date" not in frame.columns:
        raise ValueError(f"provider cache for {symbol} has no date column")

    field_candidates = {
        "open": ("adjOpen", "open"),
        "high": ("adjHigh", "high"),
        "low": ("adjLow", "low"),
        "close": ("adjClose", "close"),
        "volume": ("adjVolume", "volume"),
    }
    selected: dict[str, str] = {}
    for target, candidates in field_candidates.items():
        source = next((candidate for candidate in candidates if candidate in frame.columns), None)
        if source is None:
            raise ValueError(f"provider cache for {symbol} has no {target} field")
        selected[target] = source

    out = pd.DataFrame({"date": frame["date"]})
    out["symbol"] = symbol
    for target, source in selected.items():
        out[target] = pd.to_numeric(frame[source], errors="coerce")
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True)
    out["date"] = out["date"].dt.tz_localize(None).dt.normalize()
    out = out.dropna(subset=RAW_COLUMNS).copy()
    if out.empty:
        raise ValueError(f"provider cache for {symbol} has no valid OHLCV rows")
    if (out["close"] <= 0).any():
        raise ValueError(f"provider cache for {symbol} has non-positive close")
    return out[RAW_COLUMNS].sort_values("date", kind="mergesort").reset_index(drop=True)


def _load_provider_rows(path: Path, symbol: str) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("data", payload.get("results", []))
    if not isinstance(payload, list):
        raise ValueError(f"provider cache for {symbol} is not a row list")
    return _normalise_ohlcv(pd.DataFrame(payload), symbol)


def _load_provider_snapshot(path: Path, symbol: str) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    symbols = payload.get("symbols") if isinstance(payload, dict) else None
    if not isinstance(symbols, dict) or symbol not in symbols:
        raise ValueError(f"provider snapshot has no rows for {symbol}: {path}")
    rows = symbols[symbol]
    if not isinstance(rows, list):
        raise ValueError(f"provider snapshot rows for {symbol} are not a list")
    return _normalise_ohlcv(pd.DataFrame(rows), symbol)


def _panel_integrity(frame: pd.DataFrame) -> dict[str, int]:
    dates = pd.to_datetime(frame["date"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame["volume"], errors="coerce")
    duplicate_mask = frame.duplicated(["symbol", "date"], keep=False)
    return {
        "rows": int(len(frame)),
        "symbols": int(frame["symbol"].nunique()),
        "duplicate_rows": int(duplicate_mask.sum()),
        "duplicate_keys": int(frame.loc[duplicate_mask, ["symbol", "date"]].drop_duplicates().shape[0]),
        "volume_equals_close": int((volume == close).sum()),
        "invalid_dates": int(dates.isna().sum()),
    }


def _find_clean_base(root: Path, expected_symbols: set[str]) -> tuple[Path, pd.DataFrame]:
    candidates: list[tuple[pd.Timestamp, str, Path, pd.DataFrame]] = []
    for path in sorted((root / "Data" / "harvester" / "exports").glob("*/data/cross_asset_daily_panel.parquet")):
        frame = pd.read_parquet(path, columns=RAW_COLUMNS)
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        symbols = set(frame["symbol"].dropna().astype(str))
        if symbols != expected_symbols or _panel_integrity(frame)["invalid_dates"]:
            continue
        integrity = _panel_integrity(frame)
        if integrity["duplicate_rows"] or integrity["volume_equals_close"]:
            continue
        end = frame["date"].max()
        candidates.append((end, path.parent.parent.name, path, frame))
    if not candidates:
        raise FileNotFoundError("no clean full-history cross-asset release found")
    _, _, path, frame = max(candidates, key=lambda item: (item[0], item[1]))
    return path, frame


def _read_base(root: Path, path_arg: Path | None, expected_symbols: set[str]) -> tuple[Path, pd.DataFrame]:
    if path_arg is None:
        return _find_clean_base(root, expected_symbols)
    path = path_arg if path_arg.is_absolute() else root / path_arg
    frame = pd.read_parquet(path, columns=RAW_COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    integrity = _panel_integrity(frame)
    symbols = set(frame["symbol"].dropna().astype(str))
    if symbols != expected_symbols:
        raise ValueError(f"base release symbol set does not match configured universe: {path}")
    if any(integrity[key] for key in ("invalid_dates", "duplicate_rows", "volume_equals_close")):
        raise ValueError(f"base release is not clean: {path} ({integrity})")
    return path, frame


def _atomic_write(frame: pd.DataFrame, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.stem}.",
            suffix=".parquet",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
        frame.to_parquet(temp_path, index=False)
        os.replace(temp_path, output)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def repair_panel(
    root: Path,
    *,
    symbols_arg: str | None = None,
    base_release: Path | None = None,
    provider_cache: Path | None = None,
    recent_provider_cache: Path | None = None,
    output: Path = DEFAULT_OUTPUT,
) -> dict[str, object]:
    configured = resolve_etf_universe(root)
    configured_set = set(configured)
    selected = _parse_symbols(symbols_arg, configured)
    selected_set = set(selected)
    base_path, base = _read_base(root, base_release, configured_set)

    current_path = root / output if not output.is_absolute() else output
    current = pd.read_parquet(current_path, columns=RAW_COLUMNS) if current_path.is_file() else pd.DataFrame(columns=RAW_COLUMNS)
    current_integrity = _panel_integrity(current) if not current.empty else {
        "rows": 0,
        "symbols": 0,
        "duplicate_rows": 0,
        "duplicate_keys": 0,
        "volume_equals_close": 0,
        "invalid_dates": 0,
    }

    provider_root = provider_cache or (root / DEFAULT_PROVIDER_CACHE)
    provider_root = provider_root if provider_root.is_absolute() else root / provider_root
    full_history_snapshot = provider_root.is_file()
    recent_root = recent_provider_cache
    if recent_root is None and full_history_snapshot:
        recent_root = root / DEFAULT_PROVIDER_CACHE
    if recent_root is not None and not recent_root.is_absolute():
        recent_root = root / recent_root
    base["symbol"] = base["symbol"].astype(str)
    base_max = base.groupby("symbol")["date"].max()
    provider_parts: list[pd.DataFrame] = []
    recent_provider_parts: list[pd.DataFrame] = []
    provider_files_missing: list[str] = []
    recent_provider_files_missing: list[str] = []
    provider_rows_by_symbol: dict[str, int] = {}
    recent_provider_rows_by_symbol: dict[str, int] = {}
    for symbol in selected:
        if full_history_snapshot:
            rows = _load_provider_snapshot(provider_root, symbol)
            provider_rows_by_symbol[symbol] = int(len(rows))
            provider_parts.append(rows)
        else:
            path = provider_root / f"{symbol}_raw.json"
            if not path.is_file():
                provider_files_missing.append(symbol)
                continue
            provider = _load_provider_rows(path, symbol)
            rows = provider[provider["date"] > base_max[symbol]].copy()
            provider_rows_by_symbol[symbol] = int(len(rows))
            if not rows.empty:
                provider_parts.append(rows)

        if full_history_snapshot and recent_root is not None:
            path = recent_root / f"{symbol}_raw.json"
            if not path.is_file():
                recent_provider_files_missing.append(symbol)
                continue
            recent = _load_provider_rows(path, symbol)
            # Include the base-end date so the recent provider wins ties
            # against the full-history fallback deterministically.
            rows = recent[recent["date"] >= base_max[symbol]].copy()
            recent_provider_rows_by_symbol[symbol] = int(len(rows))
            if not rows.empty:
                recent_provider_parts.append(rows)
    if provider_files_missing:
        raise FileNotFoundError(
            "missing provider raw caches: " + ",".join(provider_files_missing)
        )
    if recent_provider_files_missing:
        raise FileNotFoundError(
            "missing recent provider raw caches: " + ",".join(recent_provider_files_missing)
        )

    if full_history_snapshot:
        # A full provider snapshot is the source of truth for the selected
        # symbols, including historical OHLCV that the legacy release stored
        # as close-only rows.  Preserve unselected symbols only for explicit
        # partial runs; the default run selects the complete configured set.
        raw = base[~base["symbol"].isin(selected_set)][RAW_COLUMNS].copy()
        if provider_parts:
            raw = pd.concat([raw, *provider_parts], ignore_index=True)
        if recent_provider_parts:
            raw = pd.concat([raw, *recent_provider_parts], ignore_index=True)
    else:
        raw = base[RAW_COLUMNS].copy()
        if provider_parts:
            raw = pd.concat([raw, *provider_parts], ignore_index=True)
    raw["symbol"] = raw["symbol"].astype(str)
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce").dt.normalize()
    raw = raw.sort_values(["symbol", "date"], kind="mergesort")
    before_dedup = int(len(raw))
    raw = raw.drop_duplicates(["symbol", "date"], keep="last").reset_index(drop=True)
    duplicate_rows_removed = before_dedup - int(len(raw))

    final = compute_derived_columns(raw)
    expected_symbols = configured
    report = validate_cross_asset_panel_contract(
        final,
        expected_symbols=expected_symbols,
        require_nonempty=True,
        raise_on_error=True,
    )
    final_integrity = _panel_integrity(final)
    if final_integrity["duplicate_rows"] or final_integrity["duplicate_keys"]:
        raise ValueError(f"repaired panel still has duplicate keys: {final_integrity}")
    if final_integrity["volume_equals_close"]:
        raise ValueError(f"repaired panel still has volume==close rows: {final_integrity}")
    if list(final.columns) != PANEL_COLUMNS:
        raise ValueError(f"unexpected repaired columns: {list(final.columns)}")

    _atomic_write(final, current_path)
    return {
        "output": str(current_path),
        "base_release": str(base_path),
        "configured_symbols": configured,
        "selected_provider_symbols": selected,
        "selection_basis": "configured_33_universe_when_no_local_D1A_24_manifest",
        "provider_cache": str(provider_root),
        "provider_snapshot_mode": full_history_snapshot,
        "recent_provider_cache": str(recent_root) if recent_root is not None else None,
        "provider_rows_added": int(sum(provider_rows_by_symbol.values())),
        "provider_rows_by_symbol": provider_rows_by_symbol,
        "recent_provider_rows_added": int(sum(recent_provider_rows_by_symbol.values())),
        "recent_provider_rows_by_symbol": recent_provider_rows_by_symbol,
        "input_current_integrity": current_integrity,
        "base_integrity": _panel_integrity(base),
        "duplicate_rows_removed_during_merge": duplicate_rows_removed,
        "final_integrity": final_integrity,
        "contract": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--symbols", help="comma-separated reviewed ETF symbols; defaults to the configured universe")
    parser.add_argument("--base-release", type=Path, help="clean full-history parquet; defaults to newest clean release")
    parser.add_argument(
        "--provider-cache",
        type=Path,
        help="directory containing <SYMBOL>_raw.json or a full-history JSON snapshot",
    )
    parser.add_argument(
        "--recent-provider-cache",
        type=Path,
        help="recent provider directory to overlay when --provider-cache is a full snapshot",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = repair_panel(
        args.workspace.resolve(),
        symbols_arg=args.symbols,
        base_release=args.base_release,
        provider_cache=args.provider_cache,
        recent_provider_cache=args.recent_provider_cache,
        output=args.output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
