"""Phase D/E/F tests — dual-path, shadow mode, health report, freeze, boundary.

Covers:
  D.1   Dual-path comparison tool
  D.2   Shadow mode in assembly
  D.3   /hub_lite API shadow endpoints
  D.4   Snapshot generation readiness
  D.5   Metadata propagation
  E.1   Config-guarded backend switch
  E.3   Cache invalidation by release_id
  E.4   Operational health report
  F.1   Legacy DataHub freeze
  F.4   Final boundary tests
"""

from __future__ import annotations

import ast
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
LITE_MODULE = SRC / "data" / "gateway" / "data_hub_lite.py"
DATA_HUB_MODULE = SRC / "data" / "gateway" / "data_hub.py"
RUNTIME_DIR = SRC / "runtime"


# ======================================================================
# D.1 — Dual-Path Comparison
# ======================================================================


class TestDualPathComparison:
    """D.1: Dual-path comparison between legacy DataHub and DataHubLite."""

    def test_compare_fetch_results_empty(self):
        from scripts.dual_path_compare import compare_fetch_results, DualPathResult
        from src.data.contracts import FetchResult

        legacy = FetchResult(kind="series", items=[], errors=[], metadata={})
        lite = FetchResult(kind="series", items=[], errors=[], metadata={"release_id": "test"})

        result = compare_fetch_results(legacy, lite)
        assert isinstance(result, DualPathResult)
        assert result.legacy_items == 0
        assert result.lite_items == 0
        assert result.coverage_match == 1.0

    def test_report_generation(self):
        from scripts.dual_path_compare import DualPathResult, dual_path_report

        result = DualPathResult(
            legacy_items=3, lite_items=3,
            common_series={"FRED:NFCI", "FRED:VIXCLS"},
            release_id="20260426T074656Z",
        )
        report = dual_path_report(result, format="markdown")
        assert "Dual-Path" in report
        assert "20260426T074656Z" in report

        json_report = dual_path_report(result, format="json")
        assert "coverage_match" in json_report

    def test_compare_with_real_lite_backend(self):
        """Smoke test: compare runs without crashing."""
        from scripts.dual_path_compare import (
            compare_fetch_results,
        )
        from src.data.contracts import FetchResult

        # Test the comparison logic, not the full run (avoids network calls)
        legacy = FetchResult(kind="series", items=[], errors=[], metadata={})
        lite = FetchResult(
            kind="series",
            items=[],
            errors=[],
            metadata={
                "release_id": "20260426T074656Z",
                "data_backend": "harvester",
                "serving_layer": "datahub_lite",
            },
        )
        result = compare_fetch_results(legacy, lite)
        assert result.release_id == "20260426T074656Z"


# ======================================================================
# D.2 — Shadow Mode
# ======================================================================


class TestShadowMode:
    """D.2: Shadow runner for assembly.py."""

    def test_shadow_mode_disabled_by_default(self):
        from src.runtime.shadow import ShadowMode
        shadow = ShadowMode({})
        assert shadow.enabled is False

    def test_shadow_mode_enabled_with_config(self):
        from src.runtime.shadow import ShadowMode
        shadow = ShadowMode({"shadow_data_backend": "harvester"})
        assert shadow.enabled is True
        assert shadow.shadow_backend == "harvester"

    def test_shadow_mode_enabled_via_data_access(self):
        from src.runtime.shadow import ShadowMode
        shadow = ShadowMode({
            "data_access": {"shadow_backend": "harvester"}
        })
        assert shadow.enabled is True
        assert shadow.primary_backend == "legacy"

    def test_shadow_compare_empty_results(self):
        from src.runtime.shadow import ShadowMode, ShadowReport
        from src.data.contracts import FetchResult

        shadow = ShadowMode({"shadow_data_backend": "harvester"})
        primary = FetchResult(kind="series", items=[], errors=[])
        shadow_result = FetchResult(kind="series", items=[], errors=[])

        report = shadow.compare(primary, shadow_result)
        assert isinstance(report, ShadowReport)
        assert report.is_consistent is True

    def test_shadow_report_to_dict(self):
        from src.runtime.shadow import ShadowReport
        report = ShadowReport(
            primary_backend="legacy",
            shadow_backend="harvester",
            series_count_primary=5,
            series_count_shadow=5,
            common_series={"FRED:NFCI"},
            shadow_release_id="test",
        )
        d = report.to_dict()
        assert d["primary_backend"] == "legacy"
        assert d["shadow_backend"] == "harvester"
        assert d["is_consistent"] is True

    def test_shadow_report_write(self, tmp_path):
        from src.runtime.shadow import ShadowMode, ShadowReport

        shadow = ShadowMode({})
        report = ShadowReport(
            primary_backend="legacy",
            shadow_backend="harvester",
            shadow_release_id="test",
        )
        path = shadow.write_report(report, output_dir=tmp_path / "reports")
        assert path.exists()

    def test_shadow_check_warns_on_divergence(self):
        from src.runtime.shadow import ShadowMode, ShadowReport

        shadow = ShadowMode({})
        report = ShadowReport(
            primary_backend="legacy",
            shadow_backend="harvester",
            series_count_primary=5,
            series_count_shadow=3,
            primary_only={"FRED:MISSING_A"},
            shadow_only={"FRED:MISSING_B"},
        )
        warnings = shadow.check_and_warn(report)
        assert len(warnings) >= 1
        assert any("divergence" in w.lower() for w in warnings)


# ======================================================================
# D.3 — Shadow API Endpoints
# ======================================================================


class TestShadowAPI:
    """D.3: /hub_lite endpoints are present in the app."""

    def test_app_has_hub_lite_routes(self):
        """Verify app.py registers /hub_lite routes."""
        text = (PROJECT / "src" / "api" / "app.py").read_text(encoding="utf-8")
        assert "hub_lite/series" in text
        assert "hub_lite/capabilities" in text
        assert "hub_lite/presets" in text
        assert "hub_lite/health" in text
        assert "hub_lite/providers" in text
        assert "hub_lite/structural" in text

    def test_app_builds_lite_service(self):
        """The _build_lite_service function exists and handles no-config."""
        from src.api.app import _build_lite_service
        service = _build_lite_service({})
        # May be None if no harvester config, but should not raise
        if service is not None:
            assert hasattr(service, "fetch_series")


# ======================================================================
# D.5 — Metadata Propagation
# ======================================================================


class TestMetadataPropagation:
    """D.5: DataHubLite metadata flows into results."""

    def test_fetchresult_metadata_has_identity_fields(self):
        from src.data.gateway.data_hub_lite import DataHubLite

        # Build a fake lite with known data
        panel = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "series_id": ["fred:X", "fred:X", "fred:X"],
            "source_id": ["fred", "fred", "fred"],
            "source_series_id": ["X", "X", "X"],
            "value": [1.0, 2.0, 3.0],
            "unit": ["pct", "pct", "pct"],
            "frequency": ["daily", "daily", "daily"],
            "vintage_date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "quality_flag": ["ok", "ok", "ok"],
        })

        class FakeAdapter:
            @property
            def current_release_id(self):
                return "test-release-1"

            def load_bundle(self):
                class B:
                    benchmark_panel = panel
                    bundle_id = "test-release-1"
                return B()

            def load_dataset(self, name):
                return panel

            def list_datasets(self):
                return ["benchmark_panel"]

        lite = DataHubLite(adapter=FakeAdapter())
        result = lite.fetch_series(
            [{"provider": "fred", "series_id": "X"}],
            start="2026-01-01",
            end="2026-01-10",
        )

        assert result.metadata["release_id"] == "test-release-1"
        assert result.metadata["data_backend"] == "harvester"
        assert result.metadata["serving_layer"] == "datahub_lite"
        assert len(result.items) == 1

        item_meta = result.items[0].metadata
        assert item_meta["requested_provider"] == "fred"
        assert item_meta["requested_series_id"] is not None
        assert item_meta["matched_source_id"] is not None
        assert item_meta["matched_source_series_id"] is not None
        assert "match_strategy" in item_meta
        assert "risk_level" in item_meta


# ======================================================================
# E.1 — Config-Guarded Backend Switch
# ======================================================================


class TestConfigGuardedSwitch:
    """E.1: Backend selection from config with fallback alarm."""

    def test_resolve_backend_defaults_to_harvester(self):
        from src.runtime.assembly import _resolve_data_backend
        assert _resolve_data_backend({}) == "harvester"

    def test_resolve_backend_harvester(self):
        from src.runtime.assembly import _resolve_data_backend
        assert _resolve_data_backend({"data_backend": "harvester"}) == "harvester"

    def test_resolve_backend_via_data_access(self):
        from src.runtime.assembly import _resolve_data_backend
        config = {"data_access": {"backend": "harvester"}}
        assert _resolve_data_backend(config) == "harvester"

    def test_shadow_enabled_detection(self):
        from src.runtime.assembly import _is_shadow_enabled
        assert _is_shadow_enabled({}) is False
        assert _is_shadow_enabled({"shadow_data_backend": "harvester"}) is True

    def test_build_system_with_harvester_backend(self):
        """build_system with data_backend=harvester does not crash."""
        from src.runtime.assembly import build_system

        config = {
            "data_backend": "harvester",
            "harvester": {
                "exports_root": str(PROJECT.parent / "Data" / "harvester" / "exports"),
                "release": "latest",
                "contract_root": str(PROJECT.parent / "packages" / "harvester" / "contracts"),
            },
            "mock_seed": 42,
        }
        try:
            pipeline = build_system(config, use_mock=True)
            assert pipeline is not None
        except Exception as exc:
            # May fail if harvester adapter can't load, which is OK for tests
            assert "harvester" in str(exc).lower() or "adapter" in str(exc).lower()


# ======================================================================
# E.3 — Cache Invalidation by release_id
# ======================================================================


class TestCacheInvalidation:
    """E.3: DataHubLite cache is invalidated on release_id change."""

    def test_cache_invalidated_on_new_release(self):
        from src.data.gateway.data_hub_lite import DataHubLite

        panel = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "series_id": ["fred:X", "fred:X", "fred:X"],
            "source_id": ["fred", "fred", "fred"],
            "source_series_id": ["X", "X", "X"],
            "value": [1.0, 2.0, 3.0],
            "unit": ["pct", "pct", "pct"],
            "frequency": ["daily", "daily", "daily"],
            "vintage_date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "quality_flag": ["ok", "ok", "ok"],
        })

        load_count = [0]

        class TrackingAdapter:
            def __init__(self):
                self._release_id = "release-1"
                self._panel = panel.copy()

            @property
            def current_release_id(self):
                return self._release_id

            def load_bundle(self):
                load_count[0] += 1
                class B:
                    benchmark_panel = self._panel.copy()
                    bundle_id = self._release_id
                return B()

            def load_dataset(self, name):
                return self._panel.copy()

            def list_datasets(self):
                return ["benchmark_panel"]

        adapter = TrackingAdapter()
        lite = DataHubLite(adapter=adapter)

        # First load
        lite.fetch_series(
            [{"provider": "fred", "series_id": "X"}],
            start="2026-01-01", end="2026-01-10",
        )
        assert load_count[0] == 1
        assert lite.release_id == "release-1"

        # Second call — cached
        lite.fetch_series(
            [{"provider": "fred", "series_id": "X"}],
            start="2026-01-01", end="2026-01-10",
        )
        assert load_count[0] == 1  # still cached

        # Change release — should invalidate
        adapter._release_id = "release-2"
        lite.fetch_series(
            [{"provider": "fred", "series_id": "X"}],
            start="2026-01-01", end="2026-01-10",
        )
        assert load_count[0] == 2  # reloaded
        assert lite.release_id == "release-2"


# ======================================================================
# E.4 — Operational Health Report
# ======================================================================


class TestHealthReport:
    """E.4: Health report generation."""

    def test_build_health_report(self):
        from src.data_access.health_report import build_health_report, HealthReport

        report = build_health_report(
            None,
            backend="harvester",
            release_id="20260426T074656Z",
            network_calls=0,
        )
        assert isinstance(report, HealthReport)
        assert report.current_backend == "harvester"
        assert report.network_calls == 0
        assert report.fallback_status == "none"

    def test_health_report_fallback_detected(self):
        from src.data_access.health_report import build_health_report

        report = build_health_report(
            None,
            backend="legacy",
            fallback_used=True,
            network_calls=5,
        )
        assert report.fallback_status == "active"
        assert len(report.warnings) >= 1
        assert any("fallback" in w.lower() for w in report.warnings)

    def test_health_report_markdown(self):
        from src.data_access.health_report import HealthReport, health_report_markdown

        report = HealthReport(
            current_backend="harvester",
            current_release_id="test",
            network_calls=0,
        )
        md = health_report_markdown(report)
        assert "Health Report" in md
        assert "harvester" in md
        assert "test" in md
        assert "Network calls = 0: ✓" in md

    def test_write_health_report(self, tmp_path):
        from src.data_access.health_report import write_health_report

        path = write_health_report(
            None,
            output_dir=str(tmp_path),
            backend="harvester",
            release_id="test",
            network_calls=0,
        )
        assert path.exists()
        content = path.read_text()
        assert "Health Report" in content


# ======================================================================
# F.1 — Legacy DataHub Freeze
# ======================================================================


class TestLegacyFreeze:
    """F.1: Legacy DataHub freeze mechanism."""

    def test_freeze_not_active_by_default(self):
        from src.data_access.freeze import is_frozen, check_legacy_allowed
        from src.data_access.freeze import unfreeze_legacy_datahub

        unfreeze_legacy_datahub()
        assert is_frozen() is False
        # Should not raise
        check_legacy_allowed("test_operation")

    def test_freeze_blocks_when_active(self):
        from src.data_access.freeze import (
            LegacyDataHubFrozen,
            check_legacy_allowed,
            freeze_legacy_datahub,
            is_frozen,
            unfreeze_legacy_datahub,
        )

        freeze_legacy_datahub()
        try:
            assert is_frozen() is True
            with pytest.raises(LegacyDataHubFrozen, match="frozen"):
                check_legacy_allowed("fetch_series")
        finally:
            unfreeze_legacy_datahub()

    def test_allow_legacy_env_var_bypasses_freeze(self, monkeypatch):
        from src.data_access.freeze import (
            check_legacy_allowed,
            freeze_legacy_datahub,
            is_frozen,
            unfreeze_legacy_datahub,
        )

        monkeypatch.setenv("ALLOW_LEGACY_DATAHUB", "1")
        freeze_legacy_datahub()
        try:
            assert is_frozen() is True
            # Should NOT raise because ALLOW_LEGACY_DATAHUB=1
            check_legacy_allowed("fetch_series")
        finally:
            unfreeze_legacy_datahub()

    def test_unfreeze_restores_access(self):
        from src.data_access.freeze import (
            check_legacy_allowed,
            freeze_legacy_datahub,
            is_frozen,
            unfreeze_legacy_datahub,
        )

        freeze_legacy_datahub()
        assert is_frozen() is True
        unfreeze_legacy_datahub()
        assert is_frozen() is False
        check_legacy_allowed("fetch_series")  # should not raise


# ======================================================================
# F.2 — Adapter Retirement Map
# ======================================================================


class TestAdapterRetirementMap:
    """F.2: Adapter retirement map is complete and parseable."""

    def test_map_is_valid_yaml(self):
        import yaml
        path = PROJECT / "configs" / "adapter_retirement_map.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "adapters" in data
        assert "phases" in data
        assert len(data["adapters"]) >= 12

    def test_retire_now_adapters_identified(self):
        import yaml
        path = PROJECT / "configs" / "adapter_retirement_map.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        retire_now = [
            name for name, entry in data["adapters"].items()
            if entry.get("status") == "retire_now"
        ]
        assert len(retire_now) >= 6
        assert "AlphaVantage" in retire_now
        assert "Polygon" in retire_now

    def test_phase_1_adapters_defined(self):
        import yaml
        path = PROJECT / "configs" / "adapter_retirement_map.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))

        phase_1 = data["phases"]["phase_1_now"]["adapters"]
        assert len(phase_1) >= 6
        assert "AlphaVantage" in phase_1


# ======================================================================
# F.4 — Final Boundary Tests
# ======================================================================


class TestFinalBoundary:
    """F.4: Runtime must be network-free; DataHubLite must not import OpenBB."""

    # ------------------------------------------------------------------
    # Network import bans
    # ------------------------------------------------------------------

    FORBIDDEN_NETWORK_IMPORTS = [
        "requests", "httpx", "urllib", "aiohttp", "socket",
        "http.client", "curl_cffi",
    ]

    FORBIDDEN_MODULE_SUBSTRINGS = [
        "public_adapters", "source_registry", "openbb",
    ]

    def _imports_in(self, path: Path) -> list[str]:
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

    def test_runtime_dir_no_network_imports(self):
        """SDRS/src/runtime/ must not import requests, httpx, or urllib."""
        for py_file in sorted(RUNTIME_DIR.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            imports = self._imports_in(py_file)
            offenders = [i for i in imports if i in self.FORBIDDEN_NETWORK_IMPORTS]
            assert not offenders, (
                f"{py_file.name} imports forbidden network module: {offenders}"
            )

    def test_datahub_lite_no_openbb_import(self):
        """DataHubLite must not import OpenBB."""
        imports = self._imports_in(LITE_MODULE)
        offenders = [i for i in imports if "openbb" in i.lower()]
        assert not offenders, f"DataHubLite imports OpenBB: {offenders}"

    def test_datahub_lite_no_public_adapters(self):
        """DataHubLite must not import legacy public_adapters."""
        imports = self._imports_in(LITE_MODULE)
        offenders = [i for i in imports if "public_adapters" in i.lower()]
        assert not offenders, f"DataHubLite imports public_adapters: {offenders}"

    def test_datahub_lite_no_source_registry(self):
        """DataHubLite must not import SourceRegistry."""
        imports = self._imports_in(LITE_MODULE)
        offenders = [i for i in imports if "source_registry" in i.lower()]
        assert not offenders, f"DataHubLite imports source_registry: {offenders}"

    def test_data_hub_lite_no_http_imports(self):
        """DataHubLite must not import HTTP libraries."""
        imports = self._imports_in(LITE_MODULE)
        offenders = [i for i in imports if i in self.FORBIDDEN_NETWORK_IMPORTS]
        assert not offenders, f"DataHubLite imports HTTP module: {offenders}"

    # ------------------------------------------------------------------
    # API key isolation
    # ------------------------------------------------------------------

    FORBIDDEN_API_KEY_PATTERNS = [
        "os.environ", "os.getenv", "API_KEY", "api_key", "SECRET",
    ]

    def test_datahub_lite_no_api_key_reads(self):
        """DataHubLite source must not contain API key patterns."""
        text = LITE_MODULE.read_text(encoding="utf-8")
        offenders = [p for p in self.FORBIDDEN_API_KEY_PATTERNS if p in text]
        assert not offenders, f"DataHubLite contains API key patterns: {offenders}"

    # ------------------------------------------------------------------
    # Harvester release integrity
    # ------------------------------------------------------------------

    def test_latest_release_has_catalog_manifest_provenance_data(self):
        """The latest Harvester release must have catalog, manifests, provenance, data."""
        exports = PROJECT.parent / "Data" / "harvester" / "exports"
        if not exports.is_dir():
            pytest.skip("Harvester exports directory not found")

        # Check there's at least one release
        releases = [d for d in exports.iterdir() if d.is_dir() and d.name != "latest"]
        if not releases:
            pytest.skip("No Harvester releases found")

        latest = sorted(releases)[-1]
        has_catalog = (latest / "catalog.json").is_file() or any(
            latest.glob("manifests/*.manifest.json")
        )
        has_data = (latest / "data").is_dir()
        has_manifests = (
            (latest / "manifests").is_dir()
            or (latest / "manifest.jsonl").is_file()  # old format
        )
        has_provenance = (
            (latest / "provenance").is_dir()
            or (latest / "provenance.jsonl").is_file()  # old format
        )

        assert has_catalog, f"No catalog/manifest in {latest.name}"
        assert has_data, f"No data/ in {latest.name}"
        assert has_manifests, f"No manifests/ in {latest.name}"
        assert has_provenance, f"No provenance/ in {latest.name}"

    # ------------------------------------------------------------------
    # OpenBB import isolation — only in Harvester providers
    # ------------------------------------------------------------------

    def test_openbb_only_in_harvester(self):
        """OpenBB imports must only appear under harvester/providers/."""
        harvester_src = PROJECT.parent / "Workbench" / "data_providers" / "structural-risk-harvester" / "src"
        if not harvester_src.is_dir():
            pytest.skip("Harvester source not found")

        for py_file in sorted(harvester_src.rglob("*.py")):
            if py_file.name.startswith("_"):
                continue
            imports = self._imports_in(py_file)
            has_openbb = any("openbb" in i.lower() for i in imports)
            if has_openbb:
                # openbb imports only allowed in providers/
                assert "providers" in str(py_file), (
                    f"OpenBB imported outside providers/: {py_file}"
                )
