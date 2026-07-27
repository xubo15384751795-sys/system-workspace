from __future__ import annotations

import ast
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
LEGACY_ALLOWED = {
    # Legacy data modules moved to _legacy (2026-06-29)
    "src/_legacy/data/data_sources.py",
    "src/_legacy/data/public_adapters.py",
    "src/_legacy/data/external_downloads.py",
    "src/_legacy/data/bridge.py",
    "src/_legacy/data/data_hub.py",
    "src/_legacy/data/__init__.py",
    "src/_legacy/__init__.py",
    # Legacy shim adapters (re-export from _legacy)
    "src/data/adapters/__init__.py",
    "src/data/gateway/__init__.py",
    # Existing acquisition-like modules kept visible until Phase 3 inventory.
    "src/benchmarks/historical_replay.py",
    "src/research_corpus/providers/brevan_howard.py",
}
FORBIDDEN_IMPORT_PREFIXES = [
    # Legacy data sources now under _legacy — forbidden from non-legacy code
    "src.data.data_sources",
    "src.data.adapters.public_adapters",
    "data.data_sources",
    "data.adapters.public_adapters",
    "src.data.external_downloads",
    "data.external_downloads",
]
FORBIDDEN_ENV_KEYS = [
    "FRED_API_KEY",
    "ALPHAVANTAGE_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
    "POLYGON_API_KEY",
    "TIINGO_API_KEY",
    "NASDAQ_DATA_LINK_API_KEY",
]
FORBIDDEN_HTTP_TOKENS = [
    "requests.get(",
    "requests.post(",
    "httpx.get(",
    "httpx.post(",
    "urllib.request",
    "aiohttp",
]
EXTERNAL_DOWNLOADS = SRC / "_legacy" / "data" / "external_downloads.py"


def rel(path: Path) -> str:
    return path.relative_to(PROJECT).as_posix()


def iter_python_files():
    for path in SRC.rglob("*.py"):
        relative = rel(path)
        if relative in LEGACY_ALLOWED:
            continue
        if "/tests/" in relative:
            continue
        yield path


def imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def test_non_legacy_modules_do_not_import_legacy_acquisition_modules():
    offenders = []
    for path in iter_python_files():
        for module in imports_in_file(path):
            if any(module.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append((rel(path), module))
    assert not offenders, "Forbidden legacy acquisition imports:\n" + "\n".join(
        f"{path} imports {module}" for path, module in offenders
    )


def test_non_legacy_modules_do_not_read_provider_api_keys():
    offenders = []
    for path in iter_python_files():
        text = path.read_text(encoding="utf-8")
        for key in FORBIDDEN_ENV_KEYS:
            if key in text:
                offenders.append((rel(path), key))
    assert not offenders, "Provider API keys found outside legacy acquisition modules:\n" + "\n".join(
        f"{path}: {key}" for path, key in offenders
    )


def test_non_legacy_modules_do_not_perform_external_http_acquisition():
    offenders = []
    for path in iter_python_files():
        for module in imports_in_file(path):
            if module in {"requests", "httpx", "aiohttp", "urllib.request"}:
                offenders.append((rel(path), module))
    assert not offenders, "External HTTP acquisition found outside legacy modules:\n" + "\n".join(
        f"{path}: {token}" for path, token in offenders
    )


def test_data_access_does_not_import_legacy_provider_modules():
    offenders = []
    for path in (SRC / "data_access").rglob("*.py"):
        for module in imports_in_file(path):
            if any(module.startswith(prefix) for prefix in FORBIDDEN_IMPORT_PREFIXES):
                offenders.append((rel(path), module))
    assert not offenders, "src/data_access must not import legacy provider modules:\n" + "\n".join(
        f"{path} imports {module}" for path, module in offenders
    )


def test_external_downloads_is_fail_wrapper_without_active_acquisition():
    text = EXTERNAL_DOWNLOADS.read_text(encoding="utf-8")
    forbidden = FORBIDDEN_HTTP_TOKENS + FORBIDDEN_ENV_KEYS + [
        "urlopen",
        "Request(",
        "subprocess.run",
        "curl",
        "cache_path.write_text",
        "pd.read_csv",
    ]
    offenders = [token for token in forbidden if token in text]
    assert not offenders, "external_downloads.py must remain a fail wrapper; found:\n" + "\n".join(offenders)
