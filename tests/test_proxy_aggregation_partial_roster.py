from __future__ import annotations

import numpy as np
import pandas as pd

from scripts._proxy_aggregation import coupled_aggregate


def test_missing_sibling_channel_does_not_poison_available_channels() -> None:
    index = pd.date_range("2026-01-01", periods=20, freq="D")
    components = pd.DataFrame(
        {
            "m": np.linspace(-1.0, 1.0, len(index)),
            "k": np.linspace(0.5, 1.5, len(index)),
            "x": np.linspace(-0.5, 0.5, len(index)),
        },
        index=index,
    )

    result = coupled_aggregate(
        components,
        {"M": ["m"], "D_contraction": [], "K": ["k"], "X_agg": ["x"]},
    )

    assert result["D_contraction"].isna().all()
    assert result[["M", "K", "X_agg"]].notna().all().all()
