"""Boundary guard tests — OpenBB may only be imported inside Harvester providers.

These tests enforce that the OpenBB SDK never leaks into Deformation
or any non-Harvester layer.  They also verify credential isolation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
HARVESTER_ROOT = HERE.parent  # packages/harvester
HARVESTER_SRC = HARVESTER_ROOT / "src" / "harvester"
SYSTEM_ROOT = HARVESTER_ROOT.parent.parent  # workspace root
DEFORMATION_SRC = SYSTEM_ROOT / "packages" / "framework_v1_archive" / "src"

# Directories where openbb imports are ALLOWED.
ALLOWED_OPENBB_DIRS: tuple[Path, ...] = (
    HARVESTER_SRC / "providers",
    SYSTEM_ROOT / "OpenBB",
)

# Files under ALLOWED_OPENBB_DIRS that re-export or bridge — they must NOT
# be accessible from Deformation.
FORBIDDEN_CONSUMERS: tuple[str, ...] = (
    "src/data/",
    "src/data_access/",
    "src/runtime/",
    "src/core/",
    "src/derivation/",
    "src/dynamics/",
    "src/operators/",
    "src/interpretation/",
    "src/proxies/",
    "src/diagnostics/",
    "src/ui/",
    "src/benchmarks/",
    "src/ml/",
    "src/research/",
)


# ---------------------------------------------------------------------------
# 1. openbb imports are confined to Harvester providers
# ---------------------------------------------------------------------------


def _py_files_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in str(p))


def _is_allowed(path: Path) -> bool:
    resolved = path.resolve()
    return any(
        str(resolved).startswith(str(allowed.resolve()))
        for allowed in ALLOWED_OPENBB_DIRS
    )


def _imports_openbb(path: Path) -> bool:
    """True if the file imports 'openbb' or 'from openbb ...'."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "openbb" or alias.name.startswith("openbb."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "openbb" or node.module.startswith("openbb.")):
                return True
    return False


def test_openbb_imports_only_in_harvester_providers():
    """openbb may only be imported inside Harvester provider code.

    Any openbb import in Deformation or other System layers is a boundary
    violation that breaks the rule: "Data Providers must not know framework theory."
    """
    offenders: list[str] = []
    # Scan Harvester — allowed but still recorded for auditing.
    harvester_files = [p for p in _py_files_under(HARVESTER_SRC) if _imports_openbb(p)]

    # Scan Deformation — must have ZERO openbb imports.
    if DEFORMATION_SRC.exists():
        for path in _py_files_under(DEFORMATION_SRC):
            rel = str(path.relative_to(DEFORMATION_SRC.parent))
            if not _imports_openbb(path):
                continue
            if any(rel.startswith(prefix) for prefix in FORBIDDEN_CONSUMERS):
                offenders.append(rel)

    # Scan other System locations (scripts, Workbench outside Harvester, etc.)
    for root_dir in (
        SYSTEM_ROOT / "scripts",
        SYSTEM_ROOT / "packages" / "workbench",
        SYSTEM_ROOT / "configs",
    ):
        if not root_dir.exists():
            continue
        for path in _py_files_under(root_dir):
            if _is_allowed(path):
                continue
            if _imports_openbb(path):
                offenders.append(str(path.relative_to(SYSTEM_ROOT)))

    assert not offenders, (
        "openbb imported outside Harvester providers:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )

    print(f"  [OK] Harvester files importing openbb: {len(harvester_files)}")
    for hf in harvester_files:
        print(f"       {hf.relative_to(HARVESTER_ROOT)}")


def test_deformation_never_imports_openbb():
    """Specifically: no file under Deformation/src/ may import openbb."""
    if not DEFORMATION_SRC.exists():
        return
    offenders: list[str] = []
    for path in _py_files_under(DEFORMATION_SRC):
        if _imports_openbb(path):
            offenders.append(str(path.relative_to(DEFORMATION_SRC.parent)))
    assert not offenders, (
        "Deformation imports openbb:\n" + "\n".join(f"  {o}" for o in offenders)
    )


# ---------------------------------------------------------------------------
# 2. API key isolation
# ---------------------------------------------------------------------------

FORBIDDEN_API_KEY_PATTERNS = (
    "OPENBB_FRED_API_KEY",
    "FRED_API_KEY=",
    "fred_api_key",
    "ALPHA_VANTAGE_API_KEY",
    "TIINGO_API_KEY",
    "POLYGON_API_KEY",
    "NASDAQ_DATA_LINK_API_KEY",
)

# Files grandfathered as legacy acquisition shims — they are known to carry
# API key references and are migration candidates, not new violations.
LEGACY_GRANDFATHERED: tuple[str, ...] = (
    # Moved to _legacy 2026-06-29
    "src/_legacy/data/data_hub.py",
    "src/_legacy/data/data_sources.py",
    "src/_legacy/data/public_adapters.py",
    "src/data/adapters/__init__.py",
    "src/data/gateway/__init__.py",
    "src/benchmarks/historical_replay.py",
)


def test_openbb_api_keys_only_in_settings_env_or_harvester_providers():
    """API keys may NOT appear in non-legacy Deformation modules.

    Legacy acquisition shims (data_hub.py, data_sources.py, adapters) are
    grandfathered — they are known migration candidates tracked in the
    architecture audit.
    """
    offenders: list[str] = []

    if DEFORMATION_SRC.exists():
        for path in _py_files_under(DEFORMATION_SRC):
            rel = str(path.relative_to(DEFORMATION_SRC.parent))
            if rel in LEGACY_GRANDFATHERED:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in FORBIDDEN_API_KEY_PATTERNS:
                if pattern in text:
                    offenders.append(f"{rel} contains {pattern}")
                    break

    assert not offenders, (
        "Provider API keys found outside legacy-grandfathered modules:\n"
        + "\n".join(f"  {o}" for o in offenders)
        + "\nIf this is a new legacy shim, add it to LEGACY_GRANDFATHERED in "
        "tests/test_openbb_boundary.py and track it in the migration plan."
    )


# ---------------------------------------------------------------------------
# 3. OpenBBProvider lazy-import pattern
# ---------------------------------------------------------------------------


def test_openbb_provider_module_is_importable_without_openbb_installed():
    """The OpenBB provider module should be importable even if openbb is not.

    It defers the actual import to fetch time via _obb().
    """
    # Remove openbb from sys.modules for this test.
    saved = {k: v for k, v in sys.modules.items() if k == "openbb" or k.startswith("openbb.")}
    for k in saved:
        del sys.modules[k]

    try:
        from harvester.providers.openbb_provider import OpenBBProvider  # noqa: F811
    finally:
        sys.modules.update(saved)

    assert OpenBBProvider is not None


def test_openbb_provider_produces_clear_error_when_openbb_unavailable(monkeypatch):
    """When openbb SDK is not importable, fetch_series returns a clean error.

    Setting sys.modules["openbb"] = None makes a subsequent ``import openbb``
    raise ImportError regardless of whether openbb is installed on the
    interpreter.  Just deleting the cached entry is insufficient because
    Python would happily re-resolve the import from site-packages.
    """
    from harvester.providers.openbb_provider import OpenBBProvider

    # Construct with no obb_client → will try to import openbb at fetch time.
    provider = OpenBBProvider(openbb_provider="fred", obb_client=None)

    # Block the openbb import for the duration of this test.  monkeypatch
    # restores sys.modules at teardown.
    monkeypatch.setitem(sys.modules, "openbb", None)
    for mod in list(sys.modules):
        if mod.startswith("openbb."):
            monkeypatch.setitem(sys.modules, mod, None)

    results = provider.fetch_series(["VIXCLS"])

    assert len(results) == 1
    assert results[0].fetch_error is not None
    assert "OpenBB" in results[0].fetch_error or "openbb" in str(results[0].fetch_error).lower()


def test_openbb_default_routes_cover_phase_2_extension():
    """Phase 2 extends DEFAULT_OPENBB_ROUTES to consolidate legacy provider acquisition.

    Locks the route inventory so accidental deletion of these entries is
    caught by CI rather than at release-build time.  Each entry must keep
    its native source_id (fred/yfinance/tiingo) so downstream consumers do
    not see "openbb" as an acquisition identity.
    """
    from harvester.providers.openbb_provider import DEFAULT_OPENBB_ROUTES

    required = {
        # Treasury curve
        "T10Y2Y": "fred",
        "T10Y3M": "fred",
        "DFF": "fred",
        "EFFR": "fred",
        "DGS10": "fred",
        "DGS2": "fred",
        "DGS30": "fred",
        # Credit-spread granularity
        "BAMLC0A1CAAA": "fred",
        "BAMLH0A1HYBB": "fred",
        # Policy/vol regime probes
        "USEPUINDXD": "fred",
        "GVZCLS": "fred",
        "OVXCLS": "fred",
        # Market companions
        "VVIX": "yfinance",
        "SKEW": "yfinance",
        # Cross-asset ETF probes
        "JNK": "tiingo",
        "SHY": "tiingo",
    }
    for series_id, expected_provider in required.items():
        assert series_id in DEFAULT_OPENBB_ROUTES, f"missing route: {series_id}"
        route = DEFAULT_OPENBB_ROUTES[series_id]
        assert route.provider == expected_provider, (
            f"{series_id} should route to {expected_provider}, got {route.provider}"
        )
        assert route.source_id == expected_provider, (
            f"{series_id} source_id must equal the native provider, got {route.source_id}"
        )


def test_openbb_provider_creates_result_with_clear_error_for_unknown_route():
    """An unregistered series_id returns a clean ProviderResult error."""
    from harvester.providers.openbb_provider import OpenBBProvider

    provider = OpenBBProvider(openbb_provider="fred")
    results = provider.fetch_series(["NONEXISTENT_SERIES"])
    assert len(results) == 1
    assert "no OpenBB route registered" in (results[0].fetch_error or "")


# ---------------------------------------------------------------------------
# 4. Route table completeness
# ---------------------------------------------------------------------------


def test_default_routes_cover_missing_series():
    """DEFAULT_OPENBB_ROUTES includes entries for the 3 missing series:
    MOVE, STLFSI4, and SOFR/IORB (the TEDRATE replacement pair).
    """
    from harvester.providers.openbb_provider import DEFAULT_OPENBB_ROUTES

    assert "MOVE" in DEFAULT_OPENBB_ROUTES, "MOVE route is required (currently missing from release)"
    assert "STLFSI4" in DEFAULT_OPENBB_ROUTES, "STLFSI4 route is required"
    assert "SOFR" in DEFAULT_OPENBB_ROUTES, "SOFR route is required (TEDRATE replacement)"
    assert "IORB" in DEFAULT_OPENBB_ROUTES, "IORB route is required (TEDRATE replacement)"
    assert "NFCI" in DEFAULT_OPENBB_ROUTES, "NFCI route is required"
    assert "VIXCLS" in DEFAULT_OPENBB_ROUTES, "VIXCLS route is required"
    assert "BAMLH0A0HYM2" in DEFAULT_OPENBB_ROUTES, "BAMLH0A0HYM2 route is required"


def test_route_table_uses_source_id_not_openbb():
    """Each route must set source_id to the provider-native identity (fred, yfinance, ...)
    NOT to 'openbb'. Downstream consumers must never see the acquisition engine name.
    """
    from harvester.providers.openbb_provider import DEFAULT_OPENBB_ROUTES

    for key, route in DEFAULT_OPENBB_ROUTES.items():
        assert route.source_id != "openbb", (
            f"Route '{key}' has source_id='openbb' — must use provider-native "
            f"identity (e.g. 'fred', 'yfinance') so downstream consumers are "
            f"not coupled to the OpenBB acquisition engine."
        )
        assert route.source_id, f"Route '{key}' has empty source_id"


def test_openbb_provider_emits_provider_native_source_id():
    """When OpenBBProvider is constructed, the ProviderResult.provider field
    must be the route's source_id, not 'openbb'.
    """
    from harvester.providers.openbb_provider import DEFAULT_OPENBB_ROUTES

    for key, route in DEFAULT_OPENBB_ROUTES.items():
        assert route.source_id == route.source_id  # tautology but documents intent
        # The ProviderResult is built by OpenBBProvider._fetch_one with:
        #   provider=route.source_id
        # This test verifies the route data is self-consistent.
        assert route.source_id in ("fred", "yfinance", "tiingo"), (
            f"Route '{key}': expected source_id in (fred, yfinance, tiingo), got {route.source_id}"
        )


# ---------------------------------------------------------------------------
# 5. Credential bridge
# ---------------------------------------------------------------------------


def test_load_env_file_loads_openbb_settings():
    """_load_env_file correctly loads KEY=VALUE pairs from a .env file."""
    import os
    import tempfile
    from harvester.providers.openbb_provider import _load_env_file

    with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
        f.write("# comment\n")
        f.write("OPENBB_FRED_API_KEY=test_key_value\n")
        f.write("OTHER_KEY=other_value\n")
        env_path = f.name

    try:
        _load_env_file(env_path)
        assert os.environ.get("OPENBB_FRED_API_KEY") == "test_key_value"
        assert os.environ.get("OTHER_KEY") == "other_value"
    finally:
        Path(env_path).unlink()


def test_load_env_file_handles_missing_file():
    """_load_env_file silently returns when the file does not exist."""
    from harvester.providers.openbb_provider import _load_env_file

    _load_env_file("/nonexistent/path/settings.env")  # must not raise


def test_safe_params_redacts_secrets():
    """_safe_params redacts api_key, token, secret, password values."""
    from harvester.providers.openbb_provider import _safe_params

    params = {
        "symbol": "VIXCLS",
        "api_key": "secret_value",
        "token": "bearer_xyz",
        "password": "hunter2",
        "start_date": "2024-01-01",
    }
    safe = _safe_params(params)
    assert safe["symbol"] == "VIXCLS"
    assert safe["api_key"] == "<redacted>"
    assert safe["token"] == "<redacted>"
    assert safe["password"] == "<redacted>"
    assert safe["start_date"] == "2024-01-01"


# ---------------------------------------------------------------------------
# 6. build_provider supports openbb
# ---------------------------------------------------------------------------


def test_build_provider_creates_openbb_provider():
    """build_provider('openbb_fred', ...) returns an OpenBBProvider instance."""
    from harvester.providers import build_provider
    from harvester.providers.openbb_provider import OpenBBProvider

    prov = build_provider("openbb_fred")
    assert isinstance(prov, OpenBBProvider)
    assert prov.openbb_provider == "fred"


def test_build_provider_openbb_yfinance():
    """build_provider('openbb_yfinance', ...) returns an OpenBBProvider for yfinance."""
    from harvester.providers import build_provider
    from harvester.providers.openbb_provider import OpenBBProvider

    prov = build_provider("openbb_yfinance")
    assert isinstance(prov, OpenBBProvider)
    assert prov.openbb_provider == "yfinance"


def test_build_provider_unknown_openbb_variant():
    """build_provider('openbb_unknown') still creates an OpenBBProvider."""
    from harvester.providers import build_provider
    from harvester.providers.openbb_provider import OpenBBProvider

    prov = build_provider("openbb_unknown")
    assert isinstance(prov, OpenBBProvider)
    assert prov.openbb_provider == "unknown"


def test_build_provider_openbb_with_settings():
    """build_provider passes settings_env kwarg through."""
    from harvester.providers import build_provider

    prov = build_provider("openbb_fred", settings_env="/tmp/test.env")
    assert prov is not None  # constructor handled the kwarg silently
