from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml import gluonts_regime_forecaster as forecaster


def test_gluonts_regime_uses_runnable_seasonal_naive_backend(tmp_path):
    pytest.importorskip("gluonts")

    panel = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=80, freq="D"),
            "value": np.sin(np.arange(80) / 5.0) + np.linspace(0.0, 1.0, 80),
        }
    )
    panel_path = tmp_path / "panel.csv"
    panel.to_csv(panel_path, index=False)

    payload = forecaster.detect_regime_gluonts(
        panel_path,
        source_release="test_release",
        source_created_at="2026-05-17T00:00:00Z",
        prediction_length=10,
        context_length=252,
        write=False,
    )

    assert payload["method"] == "gluonts_seasonal_naive_regime"
    assert payload["provenance"]["gluonts_backend"] == "gluonts_seasonal_naive"
    assert payload["method"] != "gluonts_deepar_regime_fallback"
    assert set(payload["forecast_intervals"]) == {"50pct", "80pct", "95pct"}
    assert len(payload["forecast_intervals"]["95pct"]["lower"]) == 10
    assert 0.0 <= payload["tail_probability_lower"] <= 1.0
    assert 0.0 <= payload["tail_probability_upper"] <= 1.0
    assert 0.0 <= payload["calibrated_risk_probability"] <= 1.0
