from __future__ import annotations

from types import SimpleNamespace

import harvester.derived as derived
import pandas as pd


def test_derived_series_failure_is_visible_without_fake_success(monkeypatch, caplog) -> None:
    series = SimpleNamespace(canonical_id="TEST_DERIVED")

    def fail(*_args, **_kwargs):
        raise RuntimeError("formula failed")

    monkeypatch.setattr(derived, "compute_derived", fail)
    with caplog.at_level("WARNING"):
        panel = derived.build_derived_panel([series], pd.DataFrame())

    assert panel.empty
    assert "Derived series computation failed for TEST_DERIVED" in caplog.text
    assert "RuntimeError" in caplog.text
