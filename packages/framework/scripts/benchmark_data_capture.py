from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from src._legacy.data.data_sources import FREDDataSource


DEFAULT_SERIES = ["FRED:VIXCLS", "FRED:TEDRATE", "FRED:BAMLH0A0HYM2", "FRED:NFCI"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark real FRED graph CSV capture speed.")
    parser.add_argument("--start", default="2007-01-01")
    parser.add_argument("--end", default="2009-06-30")
    parser.add_argument("--cache-dir", default="data/raw/fred")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--clear-cache", action="store_true")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    if args.clear_cache and cache_dir.exists():
        shutil.rmtree(cache_dir)

    source = FREDDataSource(cache_dir=cache_dir, max_workers=args.workers)

    t0 = time.perf_counter()
    frame = source.fetch(DEFAULT_SERIES, args.start, args.end)
    elapsed = time.perf_counter() - t0

    print(f"series={len(DEFAULT_SERIES)} rows={len(frame)} cols={len(frame.columns)}")
    print(f"range={args.start}..{args.end}")
    print(f"cache_dir={cache_dir}")
    print(f"elapsed_sec={elapsed:.3f}")
    print(f"non_null={int(frame.notna().sum().sum())}")


if __name__ == "__main__":
    main()
