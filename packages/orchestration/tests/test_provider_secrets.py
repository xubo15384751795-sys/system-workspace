from __future__ import annotations

import os

import pytest

from orchestration.provider_secrets import load_provider_secrets


@pytest.fixture(autouse=True)
def _restore_provider_environment():
    keys = ("FRED_API_KEY", "OPENBB_FRED_API_KEY", "TIINGO_API_KEY", "MASSIVE_API_KEY")
    before = {key: os.environ.get(key) for key in keys}
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def test_load_provider_secrets_allowlists_keys_and_does_not_execute(tmp_path, monkeypatch):
    path = tmp_path / "provider.env"
    path.write_text(
        "# comments are allowed\n"
        "TIINGO_API_KEY='tiingo-test'\n"
        "MASSIVE_API_KEY=massive-test\n"
        "POLYGON_API_KEY=legacy-test\n"
        "UNSAFE=$(touch SHOULD_NOT_EXIST)\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)

    loaded = load_provider_secrets(path)

    assert loaded == ("TIINGO_API_KEY", "MASSIVE_API_KEY")
    assert os.environ["TIINGO_API_KEY"] == "tiingo-test"
    assert os.environ["MASSIVE_API_KEY"] == "massive-test"
    assert "POLYGON_API_KEY" not in os.environ
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert "UNSAFE" not in os.environ


def test_explicit_environment_wins_and_insecure_file_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "provider.env"
    path.write_text("TIINGO_API_KEY=file-value\n", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setenv("TIINGO_API_KEY", "explicit-value")

    assert load_provider_secrets(path) == ()
    assert os.environ["TIINGO_API_KEY"] == "explicit-value"


def test_load_provider_secrets_supports_default_fred_routes(tmp_path, monkeypatch):
    path = tmp_path / "provider.env"
    path.write_text(
        "FRED_API_KEY=fred-test\n"
        "OPENBB_FRED_API_KEY=openbb-fred-test\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.delenv("OPENBB_FRED_API_KEY", raising=False)

    assert load_provider_secrets(path) == ("FRED_API_KEY",)
    assert os.environ["FRED_API_KEY"] == "fred-test"
    assert "OPENBB_FRED_API_KEY" not in os.environ


def test_load_provider_secrets_normalizes_openbb_environment_alias(tmp_path, monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    monkeypatch.setenv("OPENBB_FRED_API_KEY", "openbb-fred-test")

    assert load_provider_secrets(tmp_path / "missing-provider.env") == ("FRED_API_KEY",)
    assert os.environ["FRED_API_KEY"] == "openbb-fred-test"
    assert "OPENBB_FRED_API_KEY" not in os.environ
