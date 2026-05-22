"""Layout tests for _convert_market_panel_to_qlib.

Verifies the binary directory structure (calendars / instruments /
features) matches Qlib's expected on-disk layout.  Qlib readback is
intentionally not exercised here — qlib.init() pulls heavy first-time
setup that bloats the test runtime.  A separate integration test can
exercise the full readback path with QLIB_INTEGRATION=1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


RUNNER_DIR = Path(__file__).resolve().parents[1]
if str(RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(RUNNER_DIR))

from run_qlib_benchmark import _convert_market_panel_to_qlib


@pytest.fixture
def synthetic_market_panel():
    dates = pd.date_range("2024-01-02", periods=10, freq="B")
    rows = []
    rng = np.random.default_rng(7)
    for sym in ("ALPHA", "BETA"):
        base = np.cumprod(1 + rng.normal(0, 0.01, len(dates))) * 100
        for i, d in enumerate(dates):
            rows.append({
                "instrument": sym,
                "date": d,
                "open": float(base[i] * 0.998),
                "high": float(base[i] * 1.012),
                "low": float(base[i] * 0.988),
                "close": float(base[i]),
                "volume": 1000.0 + i * 10,
                "factor": 1.0,
            })
    return pd.DataFrame(rows)


def _write_panel(tmp_path: Path, panel: pd.DataFrame) -> tuple[Path, Path]:
    sb = tmp_path / "sandbox_input"
    sb.mkdir()
    panel.to_parquet(sb / "market_panel.parquet", index=False)
    qd = tmp_path / "qlib_data"
    return sb, qd


def test_dumper_creates_calendar(tmp_path, synthetic_market_panel):
    sb, qd = _write_panel(tmp_path, synthetic_market_panel)
    _convert_market_panel_to_qlib(sb, qd)
    cal_path = qd / "calendars" / "day.txt"
    assert cal_path.is_file()
    lines = cal_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 10
    assert lines[0] == "2024-01-02"


def test_dumper_creates_instrument_file_with_three_columns(tmp_path, synthetic_market_panel):
    sb, qd = _write_panel(tmp_path, synthetic_market_panel)
    _convert_market_panel_to_qlib(sb, qd)
    instr_path = qd / "instruments" / "all.txt"
    assert instr_path.is_file()
    lines = instr_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        parts = line.split("\t")
        assert len(parts) == 3, f"each instrument line must be SYMBOL\\tSTART\\tEND, got: {line}"
        sym, start, end = parts
        assert sym in {"ALPHA", "BETA"}
        assert start <= end


def test_dumper_writes_one_bin_per_field_per_symbol(tmp_path, synthetic_market_panel):
    sb, qd = _write_panel(tmp_path, synthetic_market_panel)
    _convert_market_panel_to_qlib(sb, qd)
    features = qd / "features"
    # Symbol directory names are lowercased; field names ditto.
    for sym_lower in ("alpha", "beta"):
        sym_dir = features / sym_lower
        assert sym_dir.is_dir()
        files = sorted(p.name for p in sym_dir.glob("*.bin"))
        # 6 numeric fields written (open, high, low, close, volume, factor)
        assert files == sorted([
            "close.day.bin", "factor.day.bin", "high.day.bin",
            "low.day.bin", "open.day.bin", "volume.day.bin",
        ])


def test_bin_payload_starts_with_calendar_start_index(tmp_path, synthetic_market_panel):
    """Qlib bin format: first float is start-date index into the calendar."""
    sb, qd = _write_panel(tmp_path, synthetic_market_panel)
    _convert_market_panel_to_qlib(sb, qd)
    bin_path = qd / "features" / "alpha" / "close.day.bin"
    decoded = np.frombuffer(bin_path.read_bytes(), dtype="<f4")
    # 10 calendar slots + 1 start_idx header = 11 floats
    assert len(decoded) == 11
    assert decoded[0] == pytest.approx(0.0)  # ALPHA starts at calendar index 0
    # 10 close values follow, all positive
    assert (decoded[1:] > 0).all()


def test_dumper_falls_back_to_all_symbol_when_no_instrument_column(tmp_path):
    panel = pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=5, freq="B"),
        "close": [100, 101, 102, 103, 104],
        "volume": [10, 11, 12, 13, 14],
    })
    sb, qd = _write_panel(tmp_path, panel)
    _convert_market_panel_to_qlib(sb, qd)
    instr_path = qd / "instruments" / "all.txt"
    lines = instr_path.read_text().strip().splitlines()
    assert len(lines) == 1
    assert lines[0].split("\t")[0] == "_ALL"
    assert (qd / "features" / "_all" / "close.day.bin").is_file()


def test_dumper_is_noop_when_no_market_panel(tmp_path):
    sb = tmp_path / "sandbox_input"
    sb.mkdir()
    qd = tmp_path / "qlib_data"
    _convert_market_panel_to_qlib(sb, qd)
    # No calendar / features written
    assert not (qd / "calendars" / "day.txt").exists()


def test_dumper_handles_empty_date_column(tmp_path):
    panel = pd.DataFrame({
        "date": [],
        "instrument": [],
        "close": [],
    })
    sb, qd = _write_panel(tmp_path, panel)
    _convert_market_panel_to_qlib(sb, qd)
    # Empty calendar means dumper should bail before writing anything
    assert not (qd / "calendars" / "day.txt").exists()
