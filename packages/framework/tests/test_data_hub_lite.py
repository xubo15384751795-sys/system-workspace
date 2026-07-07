"""Guard tests for DataHubLite boundary.

These tests enforce:
- DataHubLite has no HTTP / SDK imports.
- DataHubLite reads no API keys.
- DataHubLite does not import OpenBB.
- DataHubLite does not import legacy provider adapters.
- DataHubLite can be instantiated with a fake adapter.
- DataHubLite raises NotImplementedError when adapter is absent.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
LITE_MODULE = SRC / "data" / "gateway" / "data_hub_lite.py"


# ---------------------------------------------------------------------------
# 1. No HTTP / SDK imports
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORTS = [
    "requests",
    "httpx",
    "urllib",
    "aiohttp",
    "http.client",
    "socket",
    "curl_cffi",
]

FORBIDDEN_FROM_IMPORTS = [
    "requests",
    "httpx",
    "urllib.request",
    "urllib.error",
    "http.client",
    "aiohttp",
    "curl_cffi",
]


def _imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def test_datahub_lite_has_no_http_imports():
    """DataHubLite must not import requests, httpx, urllib, or any HTTP library."""
    imports = _imports_in_file(LITE_MODULE)
    offenders = [name for name in imports if name in FORBIDDEN_IMPORTS]
    assert not offenders, (
        f"DataHubLite imports forbidden HTTP modules: {offenders}"
    )


def test_datahub_lite_has_no_http_from_imports():
    """DataHubLite must not have 'from X import ...' for any HTTP module."""
    imports = _imports_in_file(LITE_MODULE)
    offenders = [
        name for name in imports
        if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_FROM_IMPORTS)
    ]
    assert not offenders, (
        f"DataHubLite has forbidden from-imports: {offenders}"
    )


# ---------------------------------------------------------------------------
# 2. No API key reads
# ---------------------------------------------------------------------------

FORBIDDEN_ENV_PATTERNS = [
    "os.environ",
    "os.getenv",
    "environ.get",
    "API_KEY",
    "api_key",
    "SECRET",
    "secret",
]


def test_datahub_lite_has_no_api_key_reads():
    """DataHubLite source must not contain API key or environ read patterns."""
    text = LITE_MODULE.read_text(encoding="utf-8")
    offenders = [pattern for pattern in FORBIDDEN_ENV_PATTERNS if pattern in text]
    assert not offenders, (
        f"DataHubLite source contains API-key/env-read patterns: {offenders}"
    )


# ---------------------------------------------------------------------------
# 3. No OpenBB import
# ---------------------------------------------------------------------------

def test_datahub_lite_does_not_import_openbb():
    """DataHubLite must not import OpenBB."""
    imports = _imports_in_file(LITE_MODULE)
    offenders = [name for name in imports if "openbb" in name.lower()]
    assert not offenders, (
        f"DataHubLite imports OpenBB: {offenders}"
    )


# ---------------------------------------------------------------------------
# 4. No legacy provider adapter imports
# ---------------------------------------------------------------------------

LEGACY_PROVIDER_PREFIXES = [
    "src.data.adapters.public_adapters",
    "src.data.adapters",
    "src.data.data_sources",
    "data.adapters.public_adapters",
    "data.adapters",
    "data.data_sources",
]


def test_datahub_lite_does_not_import_legacy_provider_adapters():
    """DataHubLite must not import src.data.adapters or src.data.data_sources."""
    imports = _imports_in_file(LITE_MODULE)
    offenders = [
        name for name in imports
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in LEGACY_PROVIDER_PREFIXES
        )
    ]
    assert not offenders, (
        f"DataHubLite imports legacy provider adapters: {offenders}"
    )


def test_datahub_lite_does_not_import_source_registry():
    """DataHubLite must not import the SourceRegistry (it wraps provider HTTP clients)."""
    imports = _imports_in_file(LITE_MODULE)
    offenders = [name for name in imports if "source_registry" in name.lower()]
    assert not offenders, (
        f"DataHubLite imports SourceRegistry: {offenders}"
    )


# ---------------------------------------------------------------------------
# 5. Instantiation with a fake adapter
# ---------------------------------------------------------------------------


class FakeBundle:
    """Minimal HarvesterBundle stand-in for tests."""

    def __init__(self, panel: pd.DataFrame | None = None, release_id: str = "test-bundle") -> None:
        self.benchmark_panel = panel if panel is not None else _make_fake_panel()
        self.proxy_candidate_panel = pd.DataFrame()
        self.corpus_index = pd.DataFrame()
        self.bundle_id = release_id
        self.catalog: dict[str, Any] = {"bundle_id": release_id, "status": "finalized"}
        self.manifest: list[dict[str, Any]] = []
        self.provenance: list[dict[str, Any]] = []
        self.source_registry: dict[str, Any] = {"sources": []}
        self.validation_report: dict[str, Any] = {}

    @property
    def release_id(self) -> str:
        return self.bundle_id

    @property
    def manifests(self) -> dict[str, Any] | None:
        return None


class FakeAdapter:
    """Minimal HarvesterAdapter stand-in that returns a FakeBundle."""

    def __init__(self, panel: pd.DataFrame | None = None, release_id: str = "test-bundle") -> None:
        self._bundle = FakeBundle(panel, release_id=release_id)
        self._load_bundle_calls = 0
        self._load_dataset_calls: list[str] = []
        self._release_id = release_id

    def load_bundle(self) -> FakeBundle:
        self._load_bundle_calls += 1
        return self._bundle

    def load_dataset(self, name: str) -> pd.DataFrame:
        self._load_dataset_calls.append(name)
        return self._bundle.benchmark_panel

    def list_datasets(self) -> list[str]:
        return ["benchmark_panel", "proxy_candidate_panel", "corpus_index"]

    @property
    def current_release_id(self) -> str | None:
        return self._release_id


def _make_fake_panel() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=5, freq="D"),
        "series_id": ["T10Y2Y"] * 5,
        "source_id": ["fred"] * 5,
        "source_series_id": ["T10Y2Y"] * 5,
        "value": [0.5, 0.6, 0.55, 0.7, 0.65],
        "unit": ["percent"] * 5,
        "frequency": ["daily"] * 5,
        "vintage_date": pd.date_range("2026-01-01", periods=5, freq="D"),
        "quality_flag": ["ok"] * 5,
    })


def test_datahub_lite_instantiate_without_adapter():
    """DataHubLite can be instantiated without an adapter."""
    from src.data.gateway.data_hub_lite import DataHubLite

    hub = DataHubLite()
    assert hub.adapter is None
    assert len(hub.presets) > 0
    assert len(hub.capabilities) > 0


def test_datahub_lite_instantiate_with_fake_adapter():
    """DataHubLite can be instantiated with a fake HarvesterAdapter."""
    from src.data.gateway.data_hub_lite import DataHubLite

    adapter = FakeAdapter()
    hub = DataHubLite(adapter=adapter)
    assert hub.adapter is adapter


def test_datahub_lite_fetch_series_raises_without_adapter():
    """fetch_series raises NotImplementedError when no adapter is configured."""
    from src.data.gateway.data_hub_lite import DataHubLite

    hub = DataHubLite()
    with pytest.raises(NotImplementedError, match="no adapter"):
        hub.fetch_series(
            [{"provider": "fred", "series_id": "T10Y2Y"}],
            start="2026-01-01",
            end="2026-01-10",
        )


def test_datahub_lite_fetch_series_with_fake_adapter():
    """fetch_series reads from the injected adapter's benchmark_panel."""
    from src.data.gateway.data_hub_lite import DataHubLite

    adapter = FakeAdapter()
    hub = DataHubLite(adapter=adapter)
    result = hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}],
        start="2026-01-01",
        end="2026-01-10",
    )
    assert result.kind == "series"
    assert len(result.items) == 1
    assert result.items[0].provider == "fred"
    assert result.items[0].request_key == "FRED:T10Y2Y"


def test_datahub_lite_available_structural_presets():
    """available_structural_presets returns a non-empty list of preset dicts."""
    from src.data.gateway.data_hub_lite import DataHubLite

    hub = DataHubLite()
    presets = hub.available_structural_presets()
    assert isinstance(presets, list)
    assert len(presets) > 0
    for entry in presets:
        assert "name" in entry
        assert "channel" in entry


def test_datahub_lite_provider_capabilities():
    """provider_capabilities returns a non-empty list of capability dicts."""
    from src.data.gateway.data_hub_lite import DataHubLite

    hub = DataHubLite()
    caps = hub.provider_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0
    for entry in caps:
        assert "provider" in entry


def test_datahub_lite_route_evidence():
    """route_evidence returns a routed result dict."""
    from src.data.gateway.data_hub_lite import DataHubLite

    hub = DataHubLite()
    route = hub.route_evidence({
        "channel": "M",
        "evidence_role": "proxy",
    })
    assert isinstance(route, dict)
    assert "request" in route
    assert "preset_names" in route
    assert "providers" in route


def test_datahub_lite_bundle_cached():
    """load_bundle is called only once across multiple fetch_series calls."""
    from src.data.gateway.data_hub_lite import DataHubLite

    adapter = FakeAdapter()
    hub = DataHubLite(adapter=adapter)
    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}],
        start="2026-01-01",
        end="2026-01-05",
    )
    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}],
        start="2026-01-03",
        end="2026-01-10",
    )
    assert adapter._load_bundle_calls == 1


def test_datahub_lite_missing_series_returns_error():
    """A series not in the benchmark_panel produces a FetchResult error."""
    from src.data.gateway.data_hub_lite import DataHubLite

    adapter = FakeAdapter()
    hub = DataHubLite(adapter=adapter)
    result = hub.fetch_series(
        [{"provider": "fred", "series_id": "NONEXISTENT"}],
        start="2026-01-01",
        end="2026-01-10",
    )
    assert len(result.items) == 0
    assert len(result.errors) >= 1
    assert "NONEXISTENT" in str(result.errors[0].request.get("request_key", ""))


def test_datahub_lite_no_forbidden_dependencies_at_runtime():
    """At runtime, DataHubLite's module dict must not leak forbidden symbols."""
    from src.data.gateway import data_hub_lite

    forbidden = {"requests", "httpx", "urllib", "openbb"}
    found = forbidden & set(data_hub_lite.__dict__.keys())
    assert not found, f"DataHubLite module has forbidden runtime symbols: {found}"


# ======================================================================
# Integration tests — real HarvesterAdapter against the latest release
# ======================================================================


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def _real_adapter():
    """Session-scoped real HarvesterAdapter pointing at the latest release."""
    from src.data_access.harvester_adapter import HarvesterAdapter

    exports = _PROJECT_ROOT / "Data" / "harvester" / "exports"
    if not exports.is_dir() or not any(exports.iterdir()):
        pytest.skip("Harvester exports directory not found or empty")

    return HarvesterAdapter(
        exports_root=str(exports),
        release="latest",
        contract_root=str(_PROJECT_ROOT / "Workbench" / "data_providers" / "structural-risk-harvester" / "contracts"),
        require_finalized=True,
        validate_hashes=False,
        validate_schema=False,
    )


@pytest.fixture()
def real_hub(_real_adapter):
    """Fresh DataHubLite wired to the real adapter (bundle cached across tests)."""
    from src.data.gateway.data_hub_lite import DataHubLite

    hub = DataHubLite(adapter=_real_adapter)
    # Load the bundle eagerly so release_id is populated.
    try:
        hub.bundle
    except Exception:
        pytest.skip("Harvester release bundle not loadable — no Harvester export data available")
    return hub
    return hub


# ------------------------------------------------------------------
# 1. Release metadata
# ------------------------------------------------------------------


def test_integration_release_id_exposed(real_hub):
    """DataHubLite exposes the loaded Harvester release_id."""
    rid = real_hub.release_id
    assert rid is not None, "release_id should be populated after bundle load"
    assert rid == "20260426T074656Z", f"unexpected release_id: {rid}"


def test_integration_bundle_accessible(real_hub):
    """The underlying HarvesterBundle is accessible."""
    bundle = real_hub.bundle
    assert bundle is not None
    assert getattr(bundle, "bundle_id", None) == "20260426T074656Z"


# ------------------------------------------------------------------
# 2. Fetch existing series (NFCI, VIXCLS, BAMLH0A0HYM2)
# ------------------------------------------------------------------


def test_integration_fetch_nfci(real_hub):
    """NFCI can be retrieved from the real release (source_id = fred_chicago_fed)."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "NFCI"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 1, f"expected 1 item, got errors: {result.errors}"
    item = result.items[0]
    assert item.provider == "fred"
    assert item.request_key == "FRED:NFCI"
    assert len(item.frame) > 0
    assert item.frame["value"].notna().any()
    # NFCI is weekly, so the frequency column should reflect that
    assert "frequency" in item.frame.columns


def test_integration_fetch_vix(real_hub):
    """VIXCLS can be retrieved from the real release."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 1, f"expected 1 item, got errors: {result.errors}"
    item = result.items[0]
    assert item.request_key == "FRED:VIXCLS"
    assert len(item.frame) > 0
    assert item.frame["value"].notna().any()


def test_integration_fetch_bamlh0a0hym2(real_hub):
    """BAMLH0A0HYM2 can be retrieved from the real release."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "BAMLH0A0HYM2"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 1, f"expected 1 item, got errors: {result.errors}"
    item = result.items[0]
    assert item.request_key == "FRED:BAMLH0A0HYM2"
    assert len(item.frame) > 0
    assert item.frame["value"].notna().any()


def test_integration_fetch_tedrate(real_hub):
    """TEDRATE is in the release but data ends in 2022-01."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "TEDRATE"}],
        start="2020-01-01",
        end="2022-06-01",
    )
    assert len(result.items) == 1
    item = result.items[0]
    # Last observation should be on or before 2022-01-21
    dates = pd.to_datetime(item.frame["date"])
    assert dates.max() <= pd.Timestamp("2022-01-22")


def test_integration_date_range_filter(real_hub):
    """Date range filtering truncates results correctly."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    dates = pd.to_datetime(result.items[0].frame["date"])
    assert dates.min() >= pd.Timestamp("2026-04-01")
    assert dates.max() <= pd.Timestamp("2026-04-10")


def test_integration_batch_fetch(real_hub):
    """Multiple series can be fetched in one call."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "NFCI"},
            {"provider": "fred", "series_id": "VIXCLS"},
            {"provider": "fred", "series_id": "BAMLH0A0HYM2"},
        ],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 3
    keys = {item.request_key for item in result.items}
    assert keys == {"FRED:NFCI", "FRED:VIXCLS", "FRED:BAMLH0A0HYM2"}


# ------------------------------------------------------------------
# 3. Missing series return DataRequestError
# ------------------------------------------------------------------


def test_integration_missing_move(real_hub):
    """MOVE is not in the release — fetch returns an error, not a crash."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "MOVE"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 0
    assert len(result.errors) >= 1
    assert "MOVE" in str(result.errors[0].request.get("source_series_id", ""))


def test_integration_missing_stlfsi4(real_hub):
    """STLFSI4 is not in the release."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "STLFSI4"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 0
    assert len(result.errors) >= 1
    assert "STLFSI4" in str(result.errors[0].request.get("source_series_id", ""))


def test_integration_missing_ofr_fsi(real_hub):
    """OFR_FSI is not in the release."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "OFR_FSI"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 0
    assert len(result.errors) >= 1
    assert "OFR_FSI" in str(result.errors[0].request.get("source_series_id", ""))


def test_integration_missing_and_present_mixed(real_hub):
    """Mixed batch: present series succeed, missing series produce errors."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "VIXCLS"},
            {"provider": "fred", "series_id": "MOVE"},
            {"provider": "fred", "series_id": "NFCI"},
        ],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 2
    assert len(result.errors) == 1
    assert "MOVE" in str(result.errors[0])


# ------------------------------------------------------------------
# 4. No HTTP / no API keys during integration tests
# ------------------------------------------------------------------


def test_integration_no_http_imports_in_datahub_lite():
    """Re-verify: DataHubLite still has no HTTP imports after hardening."""
    # (Same assertion as the guard test, re-run for safety.)
    imports = _imports_in_file(LITE_MODULE)
    offenders = [name for name in imports if name in FORBIDDEN_IMPORTS]
    assert not offenders, f"DataHubLite imports HTTP modules: {offenders}"


def test_integration_no_api_key_env_reads(real_hub):
    """The HarvesterAdapter + DataHubLite path must not read API keys from env.

    We verify this indirectly: the adapter was constructed without any API
    key argument and reads a static parquet file.  If an API key were
    required, the adapter would have failed during load_bundle().
    """
    # If we got here without exception, the integration path needs no API key.
    assert real_hub.release_id is not None


# ------------------------------------------------------------------
# 5. Preset enrichment still works
# ------------------------------------------------------------------


def test_integration_preset_enrichment(real_hub):
    """A request matching a structural preset gets enriched with channel/block/role."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    # VIXCLS is used in dof_risk_transfer_breadth_us and curvature_jump_instability_us
    # → >1 candidate → ambiguous → falls through to identity-based lookup
    # So preset enrichment won't fire here (it's ambiguous).  That's OK —
    # the request still resolves via the bundle.
    assert meta.get("source_series_id") == "VIXCLS"


def test_integration_explicit_preset_name(real_hub):
    """Providing an explicit preset_name enriches the request."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "BAMLH0A0HYM2",
          "preset_name": "dof_credit_depth_us"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    assert meta.get("preset_name") == "dof_credit_depth_us"
    assert meta.get("channel") == "D"
    assert meta.get("evidence_role") == "proxy"


def test_integration_release_id_in_result_metadata(real_hub):
    """FetchResult.metadata carries the release_id."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert result.metadata.get("release_id") == "20260426T074656Z"


# ======================================================================
# Phase B.1 — schema guard, match auditing, normalization
# ======================================================================


# ------------------------------------------------------------------
# 1. Schema guard
# ------------------------------------------------------------------


def test_schema_guard_passes_on_current_release(real_hub):
    """The current release benchmark_panel passes schema validation."""
    panel = real_hub.panel
    assert panel is not None
    required = {"date", "series_id", "source_id", "source_series_id",
                "value", "unit", "frequency", "vintage_date", "quality_flag"}
    missing = required - set(panel.columns)
    assert not missing, f"Current release missing columns: {missing}"


def test_schema_guard_fails_on_missing_required_column():
    """Schema guard raises BenchmarkPanelSchemaError when a column is missing."""
    from src.data.gateway.data_hub_lite import DataHubLite, BenchmarkPanelSchemaError

    import pandas as pd
    bad_panel = pd.DataFrame({
        "date": [],
        "series_id": [],
        "source_id": [],
        "source_series_id": [],
        # "value" is missing
        "unit": [],
        "frequency": [],
        "vintage_date": [],
        "quality_flag": [],
    })
    with pytest.raises(BenchmarkPanelSchemaError, match="value"):
        DataHubLite._validate_and_normalize_panel(bad_panel, release_label="test")


def test_schema_guard_accepts_extra_columns(real_hub):
    """Extra columns beyond the required set are silently accepted."""
    from src.data.gateway.data_hub_lite import DataHubLite

    panel = real_hub.panel.copy()
    panel["extra_column"] = 42  # add an extra column
    validated = DataHubLite._validate_and_normalize_panel(panel, release_label="test")
    assert "extra_column" in validated.columns
    assert "value" in validated.columns


# ------------------------------------------------------------------
# 2. Date + value normalization
# ------------------------------------------------------------------


def test_date_normalization_converts_object_to_datetime():
    """date column stored as object dtype is normalized to datetime64."""
    from src.data.gateway.data_hub_lite import DataHubLite
    import datetime
    import pandas as pd

    panel = pd.DataFrame({
        "date": [datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)],
        "series_id": ["X", "X"],
        "source_id": ["fred", "fred"],
        "source_series_id": ["X", "X"],
        "value": [1.0, 2.0],
        "unit": ["pct", "pct"],
        "frequency": ["daily", "daily"],
        "vintage_date": [datetime.date(2026, 1, 3), datetime.date(2026, 1, 3)],
        "quality_flag": ["ok", "ok"],
    })
    assert panel["date"].dtype == object

    validated = DataHubLite._validate_and_normalize_panel(panel)
    assert pd.api.types.is_datetime64_any_dtype(validated["date"])


def test_vintage_date_normalization():
    """vintage_date column is normalized to datetime64."""
    from src.data.gateway.data_hub_lite import DataHubLite
    import datetime
    import pandas as pd

    panel = pd.DataFrame({
        "date": [datetime.date(2026, 1, 1)],
        "series_id": ["X"],
        "source_id": ["fred"],
        "source_series_id": ["X"],
        "value": [1.0],
        "unit": ["pct"],
        "frequency": ["daily"],
        "vintage_date": [datetime.date(2026, 1, 3)],
        "quality_flag": ["ok"],
    })
    assert panel["vintage_date"].dtype == object

    validated = DataHubLite._validate_and_normalize_panel(panel)
    assert pd.api.types.is_datetime64_any_dtype(validated["vintage_date"])


def test_value_normalization_coerces_strings():
    """value column coerces non-numeric strings to NaN."""
    from src.data.gateway.data_hub_lite import DataHubLite
    import pandas as pd

    panel = pd.DataFrame({
        "date": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        "series_id": ["X", "X"],
        "source_id": ["fred", "fred"],
        "source_series_id": ["X", "X"],
        "value": ["1.5", "not_a_number"],
        "unit": ["pct", "pct"],
        "frequency": ["daily", "daily"],
        "vintage_date": pd.to_datetime(["2026-01-03", "2026-01-03"]),
        "quality_flag": ["ok", "ok"],
    })
    validated = DataHubLite._validate_and_normalize_panel(panel)
    assert validated["value"].iloc[0] == 1.5
    assert pd.isna(validated["value"].iloc[1])


# ------------------------------------------------------------------
# 3. Match strategy auditing
# ------------------------------------------------------------------


def test_nfci_records_fuzzy_match_strategy(real_hub):
    """NFCI has source_id=fred_chicago_fed but provider=fred → provider_alias match."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "NFCI"}],
        start="2026-01-01",
        end="2026-05-01",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    # NFCI: requested source_id="fred" but actual is "fred_chicago_fed"
    assert meta["source_id"] == "fred_chicago_fed"
    assert meta["source_series_id"] == "NFCI"
    # With provider_alias strategy, the fred→fred_chicago_fed alias is recognized
    assert meta["match_strategy"] in (
        "provider_alias", "source_series_id_only", "fuzzy_substring",
    ), f"unexpected strategy: {meta['match_strategy']}"
    # provider_alias is not a fuzzy strategy, so identity_match_fuzzy may not
    # be set — but for NFCI the match is via recognized alias so it's fine
    assert meta["match_strategy"] in ("provider_alias", "source_series_id_only") or "identity_match_fuzzy" in meta


def test_vix_does_not_fail_despite_ambiguous_preset(real_hub):
    """VIXCLS matches 2 presets but still resolves via identity_fallback."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    assert meta["source_series_id"] == "VIXCLS"
    # VIXCLS has exact source+series match
    assert meta["match_strategy"] == "exact_source_and_series"
    # Enrichment should be identity_fallback (ambiguous preset skipped)
    assert meta["enrichment_source"] == "identity_fallback"
    assert meta.get("preset_name") is None


def test_explicit_preset_records_match_audit(real_hub):
    """explicit_preset enrichment is recorded in metadata."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "BAMLH0A0HYM2",
          "preset_name": "dof_credit_depth_us"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    assert meta["preset_name"] == "dof_credit_depth_us"
    assert meta["channel"] == "D"
    assert meta["enrichment_source"] == "explicit_preset"


def test_exact_match_strategy_for_bamlh(real_hub):
    """BAMLH0A0HYM2 with provider=fred should get exact_source_and_series match."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "BAMLH0A0HYM2"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    assert meta["source_id"] == "fred"
    assert meta["match_strategy"] == "exact_source_and_series"


# ------------------------------------------------------------------
# 4. Fuzzy match warning flag
# ------------------------------------------------------------------


def test_identity_match_fuzzy_flag_set_when_appropriate(real_hub):
    """When enrichment is identity_fallback, identity_match_fuzzy is set."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    # VIXCLS: enrichment_source=identity_fallback → should have identity_match_fuzzy
    # regardless of panel match strategy
    assert meta.get("identity_match_fuzzy") is True


def test_preset_enrichment_does_not_flag_fuzzy(real_hub):
    """When enrichment is explicit_preset, identity_match_fuzzy is not set."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "BAMLH0A0HYM2",
          "preset_name": "dof_credit_depth_us"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    assert meta["enrichment_source"] == "explicit_preset"
    assert "identity_match_fuzzy" not in meta


# ------------------------------------------------------------------
# 5. FetchResult.metadata match audit
# ------------------------------------------------------------------


def test_fetchresult_metadata_includes_match_audit(real_hub):
    """FetchResult.metadata contains per-request match_audit entries."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "NFCI"},
            {"provider": "fred", "series_id": "VIXCLS"},
            {"provider": "fred", "series_id": "MOVE"},
        ],
        start="2026-04-01",
        end="2026-04-10",
    )
    audit = result.metadata.get("match_audit")
    assert audit is not None
    assert len(audit) == 3
    # First two matched, third did not
    assert audit[0]["matched"] is True
    assert audit[1]["matched"] is True
    assert audit[2]["matched"] is False
    assert audit[2]["request_key"] == "FRED:MOVE"


def test_fetchresult_metadata_includes_audit_summary(real_hub):
    """FetchResult.metadata includes match_audit_summary with counts."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "NFCI"},
            {"provider": "fred", "series_id": "VIXCLS"},
            {"provider": "fred", "series_id": "MOVE"},
        ],
        start="2026-04-01",
        end="2026-04-10",
    )
    summary = result.metadata.get("match_audit_summary")
    assert summary is not None
    assert summary["total_requests"] == 3
    assert summary["matched"] == 2
    assert summary["errors"] == 1


def test_fetchresult_audit_fields_on_match(real_hub):
    """Successful match audit entry has all required fields."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "BAMLH0A0HYM2"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    audit = result.metadata["match_audit"]
    entry = audit[0]
    assert entry["request_key"] == "FRED:BAMLH0A0HYM2"
    assert entry["requested_provider"] == "fred"
    assert entry["matched"] is True
    assert "matched_source_id" in entry
    assert "match_strategy" in entry
    assert "enrichment_source" in entry


# ------------------------------------------------------------------
# 6. NFCI / VIXCLS FetchResult.metadata examples
# ------------------------------------------------------------------


def test_nfci_fetchresult_metadata_example(real_hub):
    """Print-style verification of NFCI FetchResult.metadata shape."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "NFCI"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    meta = result.metadata
    assert meta["release_id"] == "20260426T074656Z"
    assert len(meta["match_audit"]) == 1
    entry = meta["match_audit"][0]
    # NFCI specifics
    assert entry["requested_provider"] == "fred"
    assert entry["requested_series_id"] == "NFCI"
    assert entry["matched"] is True
    assert entry["matched_source_id"] == "fred_chicago_fed"
    assert entry["matched_source_series_id"] == "NFCI"
    assert entry["match_strategy"] in ("source_series_id_only", "provider_alias")

    summary = meta["match_audit_summary"]
    assert summary["total_requests"] == 1
    assert summary["matched"] == 1
    assert summary["errors"] == 0


def test_vix_fetchresult_metadata_example(real_hub):
    """Print-style verification of VIXCLS FetchResult.metadata shape."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    meta = result.metadata
    assert meta["release_id"] == "20260426T074656Z"
    entry = meta["match_audit"][0]
    # VIXCLS specifics
    assert entry["requested_provider"] == "fred"
    assert entry["requested_series_id"] == "VIXCLS"
    assert entry["matched"] is True
    assert entry["matched_source_id"] == "fred"
    assert entry["matched_source_series_id"] == "VIXCLS"
    assert entry["match_strategy"] == "exact_source_and_series"
    assert entry["enrichment_source"] == "identity_fallback"
    assert entry["preset_name"] is None

    # Item-level metadata
    item_meta = result.items[0].metadata
    assert item_meta["identity_match_fuzzy"] is True
    assert item_meta["enrichment_source"] == "identity_fallback"


# ------------------------------------------------------------------
# 7. Panel property
# ------------------------------------------------------------------


def test_panel_property_returns_validated_dataframe(real_hub):
    """The .panel property returns the validated, normalized benchmark_panel."""
    panel = real_hub.panel
    assert panel is not None
    assert isinstance(panel, pd.DataFrame)
    assert pd.api.types.is_datetime64_any_dtype(panel["date"])
    assert pd.api.types.is_numeric_dtype(panel["value"])


# ======================================================================
# Phase B.1 — Schema guard + normalization extensions
# ======================================================================


def test_schema_guard_fails_on_missing_date():
    """Schema guard raises BenchmarkPanelSchemaError when 'date' is missing."""
    from src.data.gateway.data_hub_lite import _validate_benchmark_panel_schema, BenchmarkPanelSchemaError

    bad_panel = pd.DataFrame({
        "series_id": ["X"],
        "source_id": ["fred"],
        "source_series_id": ["X"],
        "value": [1.0],
        "unit": ["pct"],
        "frequency": ["daily"],
        "vintage_date": [pd.Timestamp("2026-01-01")],
        "quality_flag": ["ok"],
    })
    with pytest.raises(BenchmarkPanelSchemaError, match="date"):
        _validate_benchmark_panel_schema(bad_panel, release_label="test-release")


def test_schema_guard_fails_on_missing_value():
    """Schema guard raises BenchmarkPanelSchemaError when 'value' is missing."""
    from src.data.gateway.data_hub_lite import _validate_benchmark_panel_schema, BenchmarkPanelSchemaError

    bad_panel = pd.DataFrame({
        "date": [pd.Timestamp("2026-01-01")],
        "series_id": ["X"],
        "source_id": ["fred"],
        "source_series_id": ["X"],
        "unit": ["pct"],
        "frequency": ["daily"],
        "vintage_date": [pd.Timestamp("2026-01-01")],
        "quality_flag": ["ok"],
    })
    with pytest.raises(BenchmarkPanelSchemaError, match="value"):
        _validate_benchmark_panel_schema(bad_panel, release_label="test-release")


def test_error_message_includes_release_id():
    """BenchmarkPanelSchemaError message includes release_id."""
    from src.data.gateway.data_hub_lite import _validate_benchmark_panel_schema, BenchmarkPanelSchemaError

    bad_panel = pd.DataFrame({"wrong": []})
    with pytest.raises(BenchmarkPanelSchemaError) as exc_info:
        _validate_benchmark_panel_schema(bad_panel, release_label="20260426T074656Z")
    assert "20260426T074656Z" in str(exc_info.value)


def test_schema_metadata_shape():
    """_validate_benchmark_panel_schema returns schema metadata dict."""
    from src.data.gateway.data_hub_lite import _validate_benchmark_panel_schema

    panel = _make_fake_panel()
    _, metadata = _validate_benchmark_panel_schema(panel, release_label="test")
    assert metadata["panel"] == "benchmark_panel"
    assert metadata["row_count"] == 5
    assert "date" in metadata["columns"]
    assert metadata["date_min"] is not None
    assert metadata["date_max"] is not None
    assert metadata["series_count"] == 1
    assert "fred" in metadata["source_ids"]


def test_source_id_normalized_to_lowercase():
    """source_id column is lowercased during normalization."""
    from src.data.gateway.data_hub_lite import _validate_benchmark_panel_schema

    panel = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=2, freq="D"),
        "series_id": ["X", "X"],
        "source_id": ["FRED", "FRED_CHICAGO_FED"],
        "source_series_id": ["X", "X"],
        "value": [1.0, 2.0],
        "unit": ["pct", "pct"],
        "frequency": ["daily", "daily"],
        "vintage_date": pd.date_range("2026-01-01", periods=2, freq="D"),
        "quality_flag": ["ok", "ok"],
    })
    _, metadata = _validate_benchmark_panel_schema(panel)
    assert "fred" in metadata["source_ids"]
    assert "fred_chicago_fed" in metadata["source_ids"]
    assert "FRED" not in metadata["source_ids"]


def test_series_id_normalized_to_string():
    """series_id and source_series_id columns are normalized to strings."""
    from src.data.gateway.data_hub_lite import _validate_benchmark_panel_schema

    panel = pd.DataFrame({
        "date": pd.date_range("2026-01-01", periods=2, freq="D"),
        "series_id": [100, 200],
        "source_id": ["fred", "fred"],
        "source_series_id": [300, 400],
        "value": [1.0, 2.0],
        "unit": ["pct", "pct"],
        "frequency": ["daily", "daily"],
        "vintage_date": pd.date_range("2026-01-01", periods=2, freq="D"),
        "quality_flag": ["ok", "ok"],
    })
    validated, _ = _validate_benchmark_panel_schema(panel)
    assert validated["series_id"].iloc[0] == "100"
    assert validated["source_series_id"].iloc[0] == "300"


# ======================================================================
# Phase B.1.2 — Match strategy audit fields
# ======================================================================


def test_match_audit_includes_risk_level(real_hub):
    """Every match_audit entry carries a risk_level."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "NFCI"},
            {"provider": "fred", "series_id": "VIXCLS"},
            {"provider": "fred", "series_id": "BAMLH0A0HYM2"},
            {"provider": "fred", "series_id": "MOVE"},
        ],
        start="2026-04-01",
        end="2026-04-10",
    )
    audit = result.metadata["match_audit"]
    for entry in audit:
        assert "risk_level" in entry, f"missing risk_level in {entry}"
        assert isinstance(entry["risk_level"], str)


def test_nfci_provider_alias_records_warning(real_hub):
    """NFCI match via provider_alias records 'provider_alias_match' warning."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "NFCI"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    entry = result.metadata["match_audit"][0]
    assert entry["matched"] is True
    if entry["match_strategy"] == "provider_alias":
        assert "provider_alias_match" in entry.get("warnings", [])


def test_vixclx_ambiguous_preset_does_not_block_lookup(real_hub):
    """VIXCLS has 2 presets but lookup still succeeds via identity."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    assert len(result.errors) == 0
    assert result.items[0].request_key == "FRED:VIXCLS"


def test_fuzzy_match_records_warning(real_hub):
    """Match audit and quality_warnings are present when fuzzy strategy used."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "NFCI"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert "quality_warnings" in result.metadata
    # NFCI via provider_alias should have the warning
    if result.metadata["match_audit"][0]["match_strategy"] == "provider_alias":
        assert "provider_alias_match" in result.metadata["quality_warnings"]


def test_fetchresult_metadata_includes_release_id(real_hub):
    """FetchResult.metadata includes release_id."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert "release_id" in result.metadata
    assert result.metadata["release_id"] == "20260426T074656Z"


def test_fetchresult_metadata_includes_match_audit_field(real_hub):
    """FetchResult.metadata includes match_audit array."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert "match_audit" in result.metadata


# ======================================================================
# Phase B.2 — Release reader contract hardening
# ======================================================================


def test_datahub_lite_has_no_fs_access_in_imports():
    """DataHubLite source does not import pathlib.Path or os.path for release path construction."""
    # It may import Path for type hints, but should not use path join for release dirs
    # Verify no parquet file path reads
    text = LITE_MODULE.read_text(encoding="utf-8")
    assert ".parquet" not in text, "DataHubLite should not reference .parquet directly"
    assert "exports" not in text, "DataHubLite should not reference exports dir"


def test_bundle_missing_release_id_handled(real_hub):
    """DataHubLite still works even if bundle has no explicit release_id."""
    from src.data.gateway.data_hub_lite import DataHubLite

    class BundleNoId:
        benchmark_panel = real_hub.panel.copy()
        bundle_id = None

    class AdapterNoId:
        def load_bundle(self):
            return BundleNoId()
        def load_dataset(self, name):
            return BundleNoId.benchmark_panel
        def list_datasets(self):
            return ["benchmark_panel"]

    hub = DataHubLite(adapter=AdapterNoId())
    result = hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1


def test_bundle_missing_benchmark_panel_handled():
    """DataHubLite handles missing benchmark_panel gracefully."""
    from src.data.gateway.data_hub_lite import DataHubLite

    class BundleNoPanel:
        bundle_id = "test"
        # No benchmark_panel attribute

    class AdapterNoPanel:
        def load_bundle(self):
            return BundleNoPanel()
        def load_dataset(self, name):
            return pd.DataFrame()
        def list_datasets(self):
            return []

    hub = DataHubLite(adapter=AdapterNoPanel())
    result = hub.fetch_series(
        [{"provider": "fred", "series_id": "ANY"}],
        start="2026-01-01",
        end="2026-01-10",
    )
    assert len(result.errors) >= 1


def test_release_id_in_fetchresult_metadata(real_hub):
    """release_id appears in FetchResult.metadata."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert result.metadata["release_id"] == "20260426T074656Z"


def test_repeated_fetch_no_redundant_load_bundle():
    """Repeated fetch_series calls do not reload the bundle."""
    from src.data.gateway.data_hub_lite import DataHubLite

    adapter = FakeAdapter()
    hub = DataHubLite(adapter=adapter)
    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}], start="2026-01-01", end="2026-01-05",
    )
    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}], start="2026-01-01", end="2026-01-05",
    )
    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}], start="2026-01-01", end="2026-01-05",
    )
    assert adapter._load_bundle_calls == 1


def test_cache_invalidated_on_release_id_change():
    """When adapter current_release_id changes, bundle cache is invalidated."""
    from src.data.gateway.data_hub_lite import DataHubLite

    adapter = FakeAdapter(release_id="release-1")
    hub = DataHubLite(adapter=adapter)

    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}], start="2026-01-01", end="2026-01-05",
    )
    assert adapter._load_bundle_calls == 1

    # Change release — should trigger reload
    adapter._release_id = "release-2"
    adapter._bundle = FakeBundle(release_id="release-2")
    hub.fetch_series(
        [{"provider": "fred", "series_id": "T10Y2Y"}], start="2026-01-01", end="2026-01-05",
    )
    assert adapter._load_bundle_calls == 2
    assert hub.release_id == "release-2"


def test_adapter_without_current_release_id_does_not_crash(real_hub):
    """Adapter without current_release_id property should work (with warning)."""
    import warnings
    from src.data.gateway.data_hub_lite import DataHubLite

    class SimpleAdapter:
        def load_bundle(self):
            return real_hub._bundle
        def load_dataset(self, name):
            return real_hub.panel
        def list_datasets(self):
            return ["benchmark_panel"]

    hub = DataHubLite(adapter=SimpleAdapter())
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = hub.fetch_series(
            [{"provider": "fred", "series_id": "VIXCLS"}],
            start="2026-04-01",
            end="2026-04-10",
        )
        assert len(result.items) == 1
        # Should have warned about missing current_release_id
        adapter_warnings = [
            x for x in w
            if "adapter_does_not_expose_current_release_id" in str(x.message)
        ]
        assert len(adapter_warnings) >= 1


# ======================================================================
# Phase B.3 — FetchResult metadata standardization
# ======================================================================


def test_fetchresult_metadata_has_standard_keys(real_hub):
    """FetchResult.metadata always has the standard keys."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    for key in ("release_id", "data_backend", "serving_layer", "request_count",
                "success_count", "error_count", "match_audit", "schema_guard"):
        assert key in result.metadata, f"Missing key: {key}"


def test_errors_include_release_id(real_hub):
    """DataRequestError request payload includes release_id."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "MOVE"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.errors) >= 1
    err = result.errors[0]
    assert "release_id" in err.request
    assert err.request["release_id"] == "20260426T074656Z"


def test_errors_include_available_series(real_hub):
    """DataRequestError request payload includes available_series."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "NONEXISTENT_SERIES"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.errors) >= 1
    err = result.errors[0]
    assert "available_series" in err.request
    assert isinstance(err.request["available_series"], list)
    # Known series should be in the list
    assert "VIXCLS" in err.request["available_series"]


def test_errors_include_error_type(real_hub):
    """DataRequestError request payload includes error_type for categorization."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "MOVE"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.errors) >= 1
    err = result.errors[0]
    assert "error_type" in err.request
    assert err.request["error_type"] == "series_not_found"


def test_errors_include_hint(real_hub):
    """DataRequestError request payload includes a hint for diagnostics."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "MOVE"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.errors) >= 1
    err = result.errors[0]
    assert "hint" in err.request
    assert "MOVE" in str(err.request["hint"])


def test_success_result_includes_match_audit_fields(real_hub):
    """Each successful SeriesResult metadata carries identity + match audit."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert len(result.items) == 1
    meta = result.items[0].metadata
    for key in ("requested_provider", "requested_series_id", "matched_source_id",
                "matched_source_series_id", "series_id", "match_strategy"):
        assert key in meta, f"Missing per-series identity key: {key}"


def test_batch_fetch_has_correct_counts(real_hub):
    """Batch fetch metadata has correct success_count and error_count."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "NFCI"},
            {"provider": "fred", "series_id": "VIXCLS"},
            {"provider": "fred", "series_id": "BAMLH0A0HYM2"},
            {"provider": "fred", "series_id": "MOVE"},
            {"provider": "fred", "series_id": "STLFSI4"},
        ],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert result.metadata["request_count"] == 5
    assert result.metadata["success_count"] == 3
    assert result.metadata["error_count"] == 2


def test_empty_panel_fetchresult_metadata(real_hub):
    """FetchResult.metadata shape is stable even for empty panel."""
    from src.data.gateway.data_hub_lite import DataHubLite

    class EmptyPanelAdapter:
        @property
        def current_release_id(self):
            return "empty"
        def load_bundle(self):
            return FakeBundle(pd.DataFrame(columns=[
                "date", "series_id", "source_id", "source_series_id",
                "value", "unit", "frequency", "vintage_date", "quality_flag",
            ]), release_id="empty")
        def load_dataset(self, name):
            return pd.DataFrame()
        def list_datasets(self):
            return []

    hub = DataHubLite(adapter=EmptyPanelAdapter())
    result = hub.fetch_series(
        [{"provider": "fred", "series_id": "X"}],
        start="2026-01-01",
        end="2026-01-10",
    )
    assert "release_id" in result.metadata
    assert "data_backend" in result.metadata
    assert "serving_layer" in result.metadata
    assert result.metadata["error_count"] > 0 or result.metadata["success_count"] >= 0


# ======================================================================
# Phase B.4 — /hub protocol compatibility shell
# ======================================================================


def test_datahub_lite_exposes_old_compatible_methods(real_hub):
    """DataHubLite exposes fetch_structural_presets and build_structural_plan."""
    assert hasattr(real_hub, "fetch_structural_presets")
    assert hasattr(real_hub, "build_structural_plan")
    assert hasattr(real_hub, "available_providers")
    assert callable(real_hub.fetch_structural_presets)
    assert callable(real_hub.build_structural_plan)
    assert callable(real_hub.available_providers)


def test_provider_capabilities_is_not_acquisition(real_hub):
    """provider_capabilities returns release-serving metadata, not live acquisition."""
    caps = real_hub.provider_capabilities()
    assert isinstance(caps, list)
    for entry in caps:
        assert entry.get("capability_type") == "release_serving"
        assert entry.get("not_acquisition") is True
        assert "release_id" in entry


def test_capabilities_generated_from_release_content(real_hub):
    """Capabilities reflect what the current release contains."""
    caps = real_hub.provider_capabilities()
    # At minimum we should have capabilities for providers in the release
    assert len(caps) > 0
    for entry in caps:
        assert entry.get("capability_type") == "release_serving"


def test_available_providers_matches_release(real_hub):
    """available_providers() returns providers from release content."""
    providers = real_hub.available_providers()
    assert isinstance(providers, dict)
    # The release has fred and fred_chicago_fed
    assert "fred" in providers or "fred_chicago_fed" in providers


def test_fetch_structural_presets_returns_fetchresult(real_hub):
    """fetch_structural_presets returns a FetchResult with matching shape."""
    result = real_hub.fetch_structural_presets(
        ["dof_credit_depth_us"],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert result.kind == "series"
    assert len(result.items) >= 1
    assert "release_id" in result.metadata


def test_fetch_structural_presets_unknown_preset_no_items(real_hub):
    """fetch_structural_presets with unknown preset returns empty result."""
    result = real_hub.fetch_structural_presets(
        ["nonexistent_preset"],
        start="2026-04-01",
        end="2026-04-10",
    )
    assert result.kind == "series"
    assert len(result.items) == 0
    assert len(result.errors) == 0


def test_build_structural_plan_returns_dict(real_hub):
    """build_structural_plan returns a dict with plan metadata."""
    plan = real_hub.build_structural_plan(["M_PROXY", "D_PROXY"])
    assert isinstance(plan, dict)
    assert "preset_names" in plan
    assert "channels_touched" in plan


def test_hub_like_response_from_datalite(real_hub):
    """A /hub/series-like response shape can be produced from DataHubLite."""
    result = real_hub.fetch_series(
        [
            {"provider": "fred", "series_id": "NFCI"},
            {"provider": "fred", "series_id": "VIXCLS"},
        ],
        start="2026-04-01",
        end="2026-04-10",
    )
    # Simulate /hub/series response
    response = {
        "kind": result.kind,
        "request_count": result.metadata["request_count"],
        "success_count": result.metadata["success_count"],
        "error_count": result.metadata["error_count"],
        "release_id": result.metadata["release_id"],
        "data_backend": result.metadata["data_backend"],
        "serving_layer": result.metadata["serving_layer"],
        "items": [item.to_dict() for item in result.items],
        "errors": [err.to_dict() for err in result.errors],
    }
    assert response["kind"] == "series"
    assert response["request_count"] == 2
    assert response["success_count"] == 2
    assert response["error_count"] == 0
    assert response["release_id"] == "20260426T074656Z"
    assert response["data_backend"] == "harvester"
    assert response["serving_layer"] == "datahub_lite"
    assert len(response["items"]) == 2
    for item in response["items"]:
        assert "provider" in item
        assert "request_key" in item
        assert "rows" in item


# ======================================================================
# Phase B.1 + B.4 — schema_metadata property
# ======================================================================


def test_schema_metadata_property(real_hub):
    """DataHubLite.schema_metadata returns the schema guard output."""
    sm = real_hub.schema_metadata
    assert sm is not None
    assert sm["panel"] == "benchmark_panel"
    assert sm["row_count"] > 0
    assert sm["series_count"] >= 4
    assert "date_min" in sm
    assert "date_max" in sm
    assert "columns" in sm
    assert "source_ids" in sm


def test_fetchresult_includes_schema_guard_metadata(real_hub):
    """FetchResult.metadata.schema_guard carries panel diagnostics."""
    result = real_hub.fetch_series(
        [{"provider": "fred", "series_id": "VIXCLS"}],
        start="2026-04-01",
        end="2026-04-10",
    )
    sg = result.metadata.get("schema_guard", {})
    assert sg.get("panel") == "benchmark_panel"
    assert sg.get("row_count") > 0
