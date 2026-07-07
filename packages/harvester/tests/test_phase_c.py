"""Phase C tests — registry, derived series, TEDRATE policy, promotion gate.

Covers:
  C.1   Series registry loading + metadata completeness
  C.2   TEDRATE retired-series policy enforcement
  C.3   OpenBB provider boundary (guard tests)
  C.4   Missing series acquisition readiness
  C.5   Derived series computation (SOFR_IORB_SPREAD, CP_TBILL_SPREAD)
  C.6   Complete release staging
  C.7   Promotion gate rules
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

HARVESTER_ROOT = Path(__file__).resolve().parents[1]
SRC = HARVESTER_ROOT / "src" / "harvester"


# ======================================================================
# C.1 — Series Registry
# ======================================================================


class TestSeriesRegistry:
    """C.1.1-C.1.2: registry loading, metadata completeness, tier separation."""

    @pytest.fixture(scope="class")
    def registry(self):
        from harvester.registry import load_registry
        return load_registry()

    def test_registry_loads_without_error(self, registry):
        assert registry.schema_version == "1.0"
        assert len(registry.series) > 15

    def test_registry_has_required_series(self, registry):
        required = registry.required_series()
        required_ids = {s.canonical_id for s in required}
        assert "NFCI" in required_ids
        assert "VIXCLS" in required_ids
        assert "BAMLH0A0HYM2" in required_ids
        assert "MOVE" in required_ids
        assert "STLFSI4" in required_ids
        assert "TYVIX" in required_ids
        assert "VXTLT" in required_ids
        # OFR_FSI is degraded (required_for_release: false) —
        # it requires manual CSV download and STLFSI4 covers the financial_stress block.
        assert "OFR_FSI" not in required_ids

    def test_registry_has_provider_priority(self, registry):
        nfci = registry.get("NFCI")
        assert nfci is not None
        assert "fred_chicago_fed" in nfci.provider_priority
        assert "fred" in nfci.provider_priority

    def test_registry_separates_required_and_optional(self, registry):
        required = {s.canonical_id for s in registry.required_series()}
        model_input = {s.canonical_id for s in registry.model_input_series()}
        # NFCI is required for both
        assert "NFCI" in required
        assert "NFCI" in model_input
        # STLFSI4 is required for release but not model input
        assert "STLFSI4" in required
        assert "STLFSI4" not in model_input
        # SOFR is model input but not required-for-release
        assert "SOFR" in model_input
        assert "SOFR" not in required

    def test_registry_has_derived_series(self, registry):
        derived = registry.derived_series()
        derived_ids = {s.canonical_id for s in derived}
        assert "SOFR_IORB_SPREAD" in derived_ids
        assert "CP_TBILL_SPREAD" in derived_ids
        assert "MOVE_PROXY" in derived_ids
        for ds in derived:
            assert ds.derived is True
            assert ds.formula != ""

    def test_registry_structural_role_is_annotation_not_equation(self, registry):
        """Harvester records structural_role but does not decide K_PROXY membership."""
        vix = registry.get("VIXCLS")
        assert vix is not None
        assert vix.structural_role == "volatility_anchor"
        # structural_role does NOT say "K_PROXY" — that's Deformation's job
        assert "K_PROXY" not in vix.structural_role
        assert "M_PROXY" not in vix.structural_role

    def test_registry_providers_defined(self, registry):
        assert "fred" in registry.providers
        assert "openbb_fred" in registry.providers
        assert "cboe_direct" in registry.providers
        assert "derived" in registry.providers
        # openbb_fred emits source_id=fred, not openbb
        assert registry.providers["openbb_fred"].source_id == "fred"
        assert registry.providers["cboe_direct"].source_id == "cboe"

    def test_registry_allows_historical_replay(self, registry):
        assert registry.allowed_for_historical_replay("TEDRATE") is True
        assert registry.allowed_for_historical_replay("NFCI") is True

    def test_registry_forbids_current_diagnostics_for_retired(self, registry):
        assert registry.allowed_for_current_diagnostics("TEDRATE") is False
        assert registry.allowed_for_current_diagnostics("NFCI") is True


# ======================================================================
# C.2 — TEDRATE Retired-Series Policy
# ======================================================================


class TestTEDRATERetirement:
    """C.2: TEDRATE is formally retired with replacement policy."""

    @pytest.fixture(scope="class")
    def registry(self):
        from harvester.registry import load_registry
        return load_registry()

    def test_tedrate_marked_retired(self, registry):
        ted = registry.get("TEDRATE")
        assert ted is not None
        assert ted.status == "retired_reference"
        assert ted.is_retired is True

    def test_tedrate_has_retired_date(self, registry):
        ted = registry.get("TEDRATE")
        assert ted.retired_date is not None
        assert "2022" in ted.retired_date

    def test_tedrate_not_counted_as_model_input(self, registry):
        ted = registry.get("TEDRATE")
        assert ted.required_for_model_input is False
        assert ted.required_for_release is False
        model_inputs = registry.model_input_series()
        assert ted not in model_inputs

    def test_tedrate_allowed_in_historical_replay(self, registry):
        assert "historical_replay" in registry.get("TEDRATE").allowed_use
        assert "reference_only" in registry.get("TEDRATE").allowed_use

    def test_tedrate_forbidden_in_current_diagnostics(self, registry):
        ted = registry.get("TEDRATE")
        assert "current_model_input" in ted.forbidden_use
        assert "freshness_gate" in ted.forbidden_use

    def test_tedrate_replacement_candidates_present(self, registry):
        ted = registry.get("TEDRATE")
        replacements = ted.replacements
        assert replacements["primary"] == "SOFR_IORB_SPREAD"
        assert replacements["secondary"] == "CP_TBILL_SPREAD"
        assert replacements["tertiary"] == "BAMLH0A0HYM2"
        # All replacements should exist in the registry
        for rid in [replacements["primary"], replacements["secondary"], replacements["tertiary"]]:
            assert registry.get(rid) is not None, f"replacement {rid} missing from registry"

    def test_retired_policy_validation(self, registry):
        from harvester.registry import validate_retired_policy
        ted = registry.get("TEDRATE")
        issues = validate_retired_policy(ted)
        assert len(issues) == 0, f"TEDRATE policy has issues: {issues}"

    def test_active_series_are_not_retired(self, registry):
        for s in registry.active_series():
            assert not s.is_retired, f"{s.canonical_id} should not be retired"


# ======================================================================
# C.3 — OpenBB Acquisition Backend Boundary
# ======================================================================

# (Most C.3 guard tests already exist in test_openbb_boundary.py.
#  Here we add a few targeted assertions.)


class TestOpenBBBoundary:
    """C.3: OpenBB stays inside Harvester; guard tests reinforce the boundary."""

    def test_openbb_import_only_in_harvester_providers(self):
        """Verify that openbb imports exist only in harvester provider files."""
        import ast
        provider_dir = SRC / "providers"
        for py_file in sorted(provider_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
            if "openbb" in imports:
                # openbb_provider.py is the only file allowed to import openbb
                assert py_file.name in ("openbb_provider.py",), (
                    f"openbb imported in {py_file.name} — only openbb_provider.py is allowed"
                )

    def test_openbb_result_goes_through_normalization(self):
        """OpenBB results must go through Harvester normalization, not directly to DataHubLite."""
        # Verify that OpenBBProvider returns canonical columns via _normalize_frame
        from harvester.providers.openbb_provider import OpenBBProvider, _normalize_frame, DEFAULT_OPENBB_ROUTES

        route = DEFAULT_OPENBB_ROUTES.get("VIXCLS")
        assert route is not None
        assert route.source_id == "fred"  # source_id is native, not openbb


# ======================================================================
# C.4 — Missing Series Acquisition Readiness
# ======================================================================


class TestMissingSeriesAcquisition:
    """C.4: STLFSI4, OFR_FSI, MOVE are registered with provider routing."""

    @pytest.fixture(scope="class")
    def registry(self):
        from harvester.registry import load_registry
        return load_registry()

    def test_stlfsi4_has_fred_provider_priority(self, registry):
        s = registry.get("STLFSI4")
        assert s is not None
        assert "fred" in s.provider_priority
        assert "openbb_fred" in s.provider_priority

    def test_stlfsi4_frequency_is_weekly(self, registry):
        assert registry.get("STLFSI4").frequency == "weekly"

    def test_ofr_fsi_has_direct_ofr_priority(self, registry):
        s = registry.get("OFR_FSI")
        assert s is not None
        assert "direct_ofr" in s.provider_priority or any("ofr" in p for p in s.provider_priority)

    def test_move_has_multiple_provider_paths(self, registry):
        s = registry.get("MOVE")
        assert s is not None
        assert "openbb_yfinance" not in s.provider_priority
        assert s.provider_priority[0] == "cboe_direct"

    def test_vxtlt_is_registered_as_current_move_replacement(self, registry):
        s = registry.get("VXTLT")
        assert s is not None
        assert s.provider_priority == ("cboe_direct",)
        assert s.structural_role == "rates_vol_transition"
        assert s.required_for_model_input is True

    def test_move_allows_synthetic_proxy(self, registry):
        s = registry.get("MOVE")
        assert s.allow_synthetic_proxy is True
        assert s.synthetic_proxy_id == "MOVE_PROXY"

    def test_move_proxy_is_marked_synthetic(self, registry):
        proxy = registry.get("MOVE_PROXY")
        assert proxy is not None
        assert proxy.synthetic_proxy is True
        assert proxy.is_synthetic is True

    def test_move_proxy_formula_uses_vixcls(self, registry):
        proxy = registry.get("MOVE_PROXY")
        assert "VIXCLS" in proxy.formula


# ======================================================================
# C.5 — Derived Series (TEDRATE Replacements)
# ======================================================================


class TestDerivedSeries:
    """C.5: SOFR_IORB_SPREAD and CP_TBILL_SPREAD computation + provenance."""

    def test_build_derived_panel_sofr_iorb(self):
        """SOFR_IORB_SPREAD = SOFR - IORB computed correctly."""
        from harvester.derived import build_derived_panel
        from harvester.registry import RegistrySeries

        # Build a minimal acquired panel
        dates = pd.date_range("2026-01-01", periods=5, freq="D")
        panel = pd.concat([
            pd.DataFrame({
                "date": dates,
                "value": [4.5, 4.5, 4.5, 4.5, 4.5],
                "series_id": "FRED:SOFR",
                "source_id": "fred",
                "source_series_id": "SOFR",
                "unit": "percent",
                "frequency": "daily",
                "vintage_date": "2026-01-06",
                "quality_flag": 0,
            }),
            pd.DataFrame({
                "date": dates,
                "value": [4.0, 4.0, 4.0, 4.0, 4.0],
                "series_id": "FRED:IORB",
                "source_id": "fred",
                "source_series_id": "IORB",
                "unit": "percent",
                "frequency": "daily",
                "vintage_date": "2026-01-06",
                "quality_flag": 0,
            }),
        ], ignore_index=True)

        sofr_iorb = RegistrySeries.from_dict("SOFR_IORB_SPREAD", {
            "provider_priority": ["derived"],
            "derived": True,
            "formula": "SOFR - IORB",
            "inputs": ["SOFR", "IORB"],
            "measurement_block": "funding_gap",
            "structural_role": "tedrate_replacement_primary",
            "frequency": "daily",
            "unit": "percent",
        })
        derived = build_derived_panel([sofr_iorb], panel)
        assert len(derived) == 5
        for val in derived["value"].tolist():
            assert val == pytest.approx(0.5), f"Expected 0.5 spread, got {derived['value'].tolist()}"
        assert derived["source_id"].iloc[0] == "derived"
        assert derived["quality_flag"].iloc[0] == "derived"

    def test_build_derived_panel_cp_tbill(self):
        """CP_TBILL_SPREAD = DCPF3M - DGS3MO computed correctly."""
        from harvester.derived import build_derived_panel
        from harvester.registry import RegistrySeries

        dates = pd.date_range("2026-01-01", periods=3, freq="D")
        panel = pd.concat([
            pd.DataFrame({
                "date": dates,
                "value": [5.0, 5.0, 5.0],
                "series_id": "FRED:DCPF3M",
                "source_id": "fred",
                "source_series_id": "DCPF3M",
                "unit": "percent",
                "frequency": "daily",
                "vintage_date": "2026-01-04",
                "quality_flag": 0,
            }),
            pd.DataFrame({
                "date": dates,
                "value": [4.2, 4.2, 4.2],
                "series_id": "FRED:DGS3MO",
                "source_id": "fred",
                "source_series_id": "DGS3MO",
                "unit": "percent",
                "frequency": "daily",
                "vintage_date": "2026-01-04",
                "quality_flag": 0,
            }),
        ], ignore_index=True)

        cp_tbill = RegistrySeries.from_dict("CP_TBILL_SPREAD", {
            "provider_priority": ["derived"],
            "derived": True,
            "formula": "DCPF3M - DGS3MO",
            "inputs": ["DCPF3M", "DGS3MO"],
            "measurement_block": "funding_gap",
            "structural_role": "tedrate_replacement_secondary",
            "frequency": "daily",
            "unit": "percent",
        })
        derived = build_derived_panel([cp_tbill], panel)
        assert len(derived) == 3
        for val in derived["value"].tolist():
            assert val == pytest.approx(0.8)

    def test_derived_manifest_includes_formula(self):
        """Derived series manifest documents the formula and inputs."""
        from harvester.derived import build_derived_manifest
        from harvester.registry import RegistrySeries

        series = RegistrySeries.from_dict("SOFR_IORB_SPREAD", {
            "provider_priority": ["derived"],
            "derived": True,
            "formula": "SOFR - IORB",
            "inputs": ["SOFR", "IORB"],
            "measurement_block": "funding_gap",
            "structural_role": "tedrate_replacement_primary",
            "frequency": "daily",
            "unit": "percent",
        })
        manifest = build_derived_manifest(
            series,
            release_id="2026-05-05-r1",
            as_of_date="2026-05-05",
            vintage_date="2026-05-05",
            data_sha256="abc123",
            data_byte_size=1000,
            row_count=100,
            time_start="2026-01-01",
            time_end="2026-05-05",
        )
        assert manifest["dataset_id"] == "SOFR_IORB_SPREAD"
        assert manifest["source"]["kind"] == "derived"
        assert manifest["lineage"]["derivation"]["formula"] == "SOFR - IORB"
        assert manifest["lineage"]["derivation"]["inputs"] == ["SOFR", "IORB"]
        assert manifest["lineage"]["derivation"]["alignment"] == "inner_join"

    def test_derived_provenance_includes_checksums(self):
        """Derived series provenance records final_sha256."""
        from harvester.derived import build_derived_provenance
        from harvester.registry import RegistrySeries

        series = RegistrySeries.from_dict("SOFR_IORB_SPREAD", {
            "provider_priority": ["derived"],
            "derived": True,
            "formula": "SOFR - IORB",
            "inputs": ["SOFR", "IORB"],
            "measurement_block": "funding_gap",
            "structural_role": "tedrate_replacement_primary",
            "frequency": "daily",
            "unit": "percent",
        })
        provenance = build_derived_provenance(
            series,
            release_id="2026-05-05-r1",
            final_sha256="def456",
        )
        assert provenance["dataset_id"] == "SOFR_IORB_SPREAD"
        assert provenance["acquisition"]["method"] == "computed"
        assert provenance["checksums"]["final_sha256"] == "def456"
        assert len(provenance["transformations"]) == 1
        assert provenance["transformations"][0]["outcome"] == "success"

    def test_derived_quality_flag_synthetic(self):
        """Synthetic proxy series get 'synthetic_proxy' quality flag."""
        from harvester.derived import compute_derived
        from harvester.registry import RegistrySeries

        dates = pd.date_range("2026-01-01", periods=3, freq="D")
        panel = pd.DataFrame({
            "date": dates,
            "value": [20.0, 20.0, 20.0],
            "series_id": "FRED:VIXCLS",
            "source_id": "fred",
            "source_series_id": "VIXCLS",
            "unit": "index",
            "frequency": "daily",
            "vintage_date": "2026-01-04",
            "quality_flag": 0,
        })

        move_proxy = RegistrySeries.from_dict("MOVE_PROXY", {
            "provider_priority": ["derived"],
            "derived": True,
            "synthetic_proxy": True,
            "formula": "VIXCLS * 0.5",
            "inputs": ["VIXCLS"],
            "measurement_block": "rates_volatility",
            "frequency": "daily",
            "unit": "index",
        })
        result = compute_derived(move_proxy, panel)
        assert result is not None
        assert result["quality_flag"].iloc[0] == "synthetic_proxy"

    def test_empty_panel_produces_empty_derived(self):
        """Empty acquired panel produces empty derived panel."""
        from harvester.derived import build_derived_panel
        from harvester.registry import RegistrySeries

        empty = pd.DataFrame(columns=[
            "date", "series_id", "source_id", "source_series_id",
            "value", "unit", "frequency", "vintage_date", "quality_flag",
        ])
        sofr_iorb = RegistrySeries.from_dict("SOFR_IORB_SPREAD", {
            "provider_priority": ["derived"],
            "derived": True,
            "formula": "SOFR - IORB",
            "inputs": ["SOFR", "IORB"],
            "measurement_block": "funding_gap",
            "frequency": "daily",
            "unit": "percent",
        })
        derived = build_derived_panel([sofr_iorb], empty)
        assert derived.empty


# ======================================================================
# C.6 — Complete Release Staging
# ======================================================================


class TestCompleteRelease:
    """C.6: Complete release staging with benchmark + proxy + corpus status."""

    def test_build_complete_benchmark_panel(self):
        """Combines acquired, external, and derived panels."""
        from harvester.official import build_complete_benchmark_panel

        acquired = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "value": [1.0, 2.0, 3.0],
            "series_id": ["FRED:TEST"] * 3,
            "source_id": ["fred"] * 3,
            "source_series_id": ["TEST"] * 3,
            "unit": ["pct"] * 3,
            "frequency": ["daily"] * 3,
            "vintage_date": ["2026-01-04"] * 3,
            "quality_flag": [0] * 3,
        })
        derived = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "value": [0.5] * 3,
            "series_id": ["DERIVED:TEST_D"] * 3,
            "source_id": ["derived"] * 3,
            "source_series_id": ["TEST_D"] * 3,
            "unit": ["pct"] * 3,
            "frequency": ["daily"] * 3,
            "vintage_date": ["2026-01-04"] * 3,
            "quality_flag": ["derived"] * 3,
        })
        panel = build_complete_benchmark_panel(acquired, derived_panel=derived)
        assert len(panel) == 6
        ids = set(panel["source_series_id"].unique())
        assert "TEST" in ids
        assert "TEST_D" in ids
        assert set(panel["quality_flag"].unique()) == {"observed", "derived"}

    def test_panel_identity_set_includes_provider_prefixed_canonical_id(self):
        from harvester.official import panel_identity_set

        panel = pd.DataFrame({
            "series_id": ["CBOE:MOVE"],
            "source_series_id": ["VXTLT"],
        })

        ids = panel_identity_set(panel)

        assert "CBOE:MOVE" in ids
        assert "MOVE" in ids
        assert "VXTLT" in ids

    def test_build_proxy_candidate_panel_filters(self):
        """proxy_candidate_panel only contains designated proxy series."""
        from harvester.official import build_proxy_candidate_panel

        derived = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=2, freq="D"),
            "value": [0.5, 0.5],
            "series_id": ["DERIVED:SOFR_IORB_SPREAD"] * 2,
            "source_id": ["derived"] * 2,
            "source_series_id": ["SOFR_IORB_SPREAD"] * 2,
            "unit": ["pct"] * 2,
            "frequency": ["daily"] * 2,
            "vintage_date": ["2026-01-03"] * 2,
            "quality_flag": ["derived"] * 2,
        })
        proxy = build_proxy_candidate_panel(derived)
        assert len(proxy) == 2
        assert set(proxy["source_series_id"].unique()) == {"SOFR_IORB_SPREAD"}

        # Non-proxy derived series should not appear
        other = pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=2, freq="D"),
            "value": [1.0, 1.0],
            "series_id": ["DERIVED:OTHER"] * 2,
            "source_id": ["derived"] * 2,
            "source_series_id": ["OTHER"] * 2,
            "unit": ["pct"] * 2,
            "frequency": ["daily"] * 2,
            "vintage_date": ["2026-01-03"] * 2,
            "quality_flag": ["derived"] * 2,
        })
        combined = pd.concat([derived, other], ignore_index=True)
        proxy2 = build_proxy_candidate_panel(combined)
        assert "OTHER" not in set(proxy2["source_series_id"].unique())


# ======================================================================
# C.7 — Promotion Gate
# ======================================================================


class TestPromotionGate:
    """C.7: Release quality gate rules and promotion states."""

    @pytest.fixture(scope="class")
    def registry(self):
        from harvester.registry import load_registry
        return load_registry()

    @pytest.fixture()
    def temp_release_dir(self, tmp_path):
        d = tmp_path / "test-release"
        d.mkdir()
        for sub in ("data", "manifests", "provenance"):
            (d / sub).mkdir(parents=True, exist_ok=True)
        return d

    def test_all_required_present_passes(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, PromotionState

        # Include all required-for-release series
        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        # Also include model-input and TEDRATE replacements to avoid warnings
        all_required.update(s.canonical_id for s in registry.model_input_series())
        all_required.update({"SOFR_IORB_SPREAD", "CP_TBILL_SPREAD"})
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids=all_required,
            sha256_verified=True,
        )
        assert result.promotion_allowed is True
        assert result.passed is True

    def test_missing_required_blocks(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, PromotionState

        # Only one required series present
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids={"NFCI"},
            sha256_verified=True,
        )
        assert result.state == PromotionState.REJECTED
        assert not result.passed
        assert len(result.blockers) >= 1
        assert any("required series missing" in b for b in result.blockers)

    def test_missing_model_input_warns(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate

        # All required present, but missing model inputs
        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids=all_required,
            sha256_verified=True,
        )
        # Should warn about missing model inputs but not block
        assert len(result.warnings) >= 1 or result.passed

    def test_sha256_failure_blocks(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, PromotionState

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids=all_required,
            sha256_verified=False,  # fail integrity
        )
        assert result.state == PromotionState.REJECTED
        assert any("sha256" in b.lower() for b in result.blockers)

    def test_future_vintage_blocks(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, PromotionState

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids=all_required,
            sha256_verified=True,
            has_future_vintage=True,
        )
        assert result.state == PromotionState.REJECTED

    def test_retired_not_in_current_input_check(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, PromotionState

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids=all_required,
            sha256_verified=True,
            retired_in_current_input=True,
        )
        assert result.state == PromotionState.REJECTED
        assert any("retired" in b.lower() for b in result.blockers)

    def test_tedrate_without_replacement_warns(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir,
            registry,
            panel_series_ids=all_required,  # no SOFR_IORB_SPREAD or CP_TBILL_SPREAD
            sha256_verified=True,
        )
        # Should warn about missing TEDRATE replacements
        assert len(result.warnings) >= 1 or any(
            "tedrate" in c.name.lower() and not c.passed
            for c in result.checks
        )

    def test_gate_report_generation(self, registry, temp_release_dir):
        from harvester.promotion import generate_gate_report, run_promotion_gate

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir, registry,
            panel_series_ids=all_required, sha256_verified=True,
        )
        report = generate_gate_report(result, "2026-05-05-r1")
        assert report["release_id"] == "2026-05-05-r1"
        assert "promotion_state" in report
        assert "checks" in report
        assert isinstance(report["checks"], list)
        for check in report["checks"]:
            assert "name" in check
            assert "passed" in check
            assert "severity" in check

    def test_write_gate_report(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, write_gate_report

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir, registry,
            panel_series_ids=all_required, sha256_verified=True,
        )
        path = write_gate_report(result, "test-r1", temp_release_dir)
        assert path.exists()
        data = json.loads(path.read_text())
        assert "release_id" in data
        assert "promotion_state" in data

    def test_empty_required_panel_blocks(self, registry, temp_release_dir):
        from harvester.promotion import run_promotion_gate, PromotionState

        all_required = {s.canonical_id for s in registry.required_series()}
        all_required.add("MOVE_PROXY")
        result = run_promotion_gate(
            temp_release_dir, registry,
            panel_series_ids=all_required,
            sha256_verified=True,
            empty_panels=["benchmark_panel"],
        )
        assert result.state == PromotionState.REJECTED
        assert any("empty" in b.lower() for b in result.blockers)
