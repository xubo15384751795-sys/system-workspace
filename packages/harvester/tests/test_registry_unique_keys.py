from __future__ import annotations

from pathlib import Path
import re


REGISTRY = Path(__file__).resolve().parents[1] / "configs" / "series_registry.yaml"


def test_series_registry_has_no_duplicate_top_level_series_keys() -> None:
    """PyYAML silently accepts duplicate keys, so guard the source text."""
    text = REGISTRY.read_text(encoding="utf-8")
    series_text = text.split("\nseries:\n", 1)[1]
    keys = re.findall(r"^  ([A-Za-z0-9_^:.-]+):\s*$", series_text, flags=re.MULTILINE)
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert duplicates == []


def test_k_surface_series_remain_model_inputs_from_cboe_direct() -> None:
    import yaml

    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    for series_id in ("SKEW", "VVIX"):
        spec = payload["series"][series_id]
        assert spec["provider_priority"][0] == "cboe_direct"
        assert spec["required_for_model_input"] is True
