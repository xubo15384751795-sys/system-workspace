"""Quick check of available data for the replay."""
import pandas as pd
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

# Check Harvester exports
exports_dir = PROJECT / "Data" / "harvester" / "exports"
releases = sorted([d for d in exports_dir.iterdir() if d.is_dir() and d.name != "latest"])
print("=== Harvester Releases ===")
for r in releases:
    print(f"  {r.name}")

# Check latest benchmark panel
latest_bm = None
for r in reversed(releases):
    bm_path = r / "data" / "benchmark_panel.parquet"
    if bm_path.exists():
        latest_bm = bm_path
        break

if latest_bm:
    bm = pd.read_parquet(latest_bm)
    print(f"\n=== Benchmark Panel ===")
    for s in sorted(bm["series_id"].unique()):
        d = bm[bm["series_id"] == s]
        print(f"  {s:20s} source={d['source_id'].iloc[0]:15s} {d['date'].min()} -> {d['date'].max()}  n={len(d)}")

# Check what FRED CSVs we have cached
fred_dir = PROJECT / "Data" / "harvester" / "raw" / "fred"
if fred_dir.is_dir():
    print(f"\n=== Cached FRED CSVs ===")
    for f in sorted(fred_dir.glob("*.csv")):
        df = pd.read_csv(f, nrows=2)
        cols = list(df.columns)
        print(f"  {f.name:30s} cols={cols}")

# Check OpenBB cache
obb_cache = PROJECT / "Data" / "harvester" / "raw" / "openbb"
if obb_cache.is_dir():
    print(f"\n=== OpenBB cache ===")
    for f in sorted(obb_cache.glob("*")):
        print(f"  {f.name}")

# Check if yfinance data from previous replay still exists
yf_cache = PROJECT / "Output" / "sandbox" / "structural_replay" / "data" / "yfinance_benchmarks.parquet"
if yf_cache.exists():
    df = pd.read_parquet(yf_cache)
    print(f"\n=== yfinance cache ===")
    print(f"  Columns: {list(df.columns)}")
    print(f"  Range: {df.index.min().date()} -> {df.index.max().date()}")
