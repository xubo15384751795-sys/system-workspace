from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.core.models import FastSignal, ProxyReading, Snapshot, StructuralState
from src.signals.fast_signal import CrossValidator, FastSignalComputer, FastSignalConfig


class FastSignalTests(unittest.TestCase):
    def test_fast_signal_computer_builds_daily_signal_from_local_raw_fred(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_dir = Path(tmpdir)
            dates = pd.date_range("2025-01-01", periods=90, freq="B")
            self._write_series(raw_dir, "DAAA", dates, np.linspace(5.0, 5.2, len(dates)))
            self._write_series(raw_dir, "DBAA", dates, np.linspace(5.8, 6.4, len(dates)))
            self._write_series(raw_dir, "DCPF3M", dates, np.linspace(4.4, 4.2, len(dates)))
            self._write_series(raw_dir, "DFF", dates, np.linspace(4.3, 4.7, len(dates)))
            self._write_series(raw_dir, "T10Y2Y", dates, np.linspace(0.6, -0.2, len(dates)))
            self._write_series(raw_dir, "VIXCLS", dates, np.linspace(15.0, 30.0, len(dates)))

            signal = FastSignalComputer(
                raw_fred_dir=raw_dir,
                config=FastSignalConfig(baseline_days=120, min_observations=20),
            ).compute("2025-05-06")

            self.assertEqual(signal.run_type, "DAILY")
            self.assertEqual(signal.date, dates[-1].strftime("%Y-%m-%d"))
            self.assertIn(signal.alert_level, {"CLEAR", "WATCH", "WARN", "ALERT"})
            self.assertIsNotNone(signal.composite)
            self.assertEqual(set(signal.directions), {"M", "D", "K", "X"})

    def test_cross_validator_classifies_confirmed_when_directions_agree(self) -> None:
        canonical = _build_snapshot("2026-04-20")
        fast = FastSignal(
            date="2026-04-20",
            M_zscore=1.2,
            D_zscore=1.1,
            K_zscore=1.0,
            X_zscore=1.3,
            composite=1.15,
            alert_level="WARN",
            threshold_hits=("M", "D", "K", "X"),
            directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        )

        validation = CrossValidator().validate(canonical=canonical, fast=fast)

        self.assertEqual(validation.verdict, "CONFIRMED")
        self.assertEqual(validation.confidence_multiplier, 1.0)

    def _write_series(self, raw_dir: Path, series_id: str, dates: pd.DatetimeIndex, values: np.ndarray) -> None:
        payload = {
            "observations": [
                {"date": date.strftime("%Y-%m-%d"), "value": str(float(value))}
                for date, value in zip(dates, values)
            ]
        }
        (raw_dir / f"{series_id}_raw.json").write_text(json.dumps(payload), encoding="utf-8")


def _build_snapshot(run_date: str) -> Snapshot:
    proxy = ProxyReading(
        run_date=run_date,
        M=0.1,
        D=0.2,
        K=0.3,
        X=0.4,
        directions={"M": "STABLE", "D": "STABLE", "K": "STABLE", "X": "STABLE"},
        available={"M": True, "D": True, "K": True, "X": True},
        components={"M": 0.1, "D": 0.2, "K": 0.3, "X": 0.4},
    )
    state = StructuralState(
        run_date=run_date,
        z_vector=np.ones(6, dtype=float),
        sigma_t=0.5,
        singular_flag=False,
        leading_channel="NONE",
        pattern="STABLE_LOCAL",
        anomaly_score=-0.1,
        reflexivity_flags={},
        provenance={},
    )
    return Snapshot(
        run_date=run_date,
        run_type="WEEKLY",
        proxy=proxy,
        state=state,
        narrative=None,
        escalation=False,
        escalation_reason=None,
    )


if __name__ == "__main__":
    unittest.main()
