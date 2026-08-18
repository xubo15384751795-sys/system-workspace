from __future__ import annotations

import os

from orchestration.provider_secrets import load_provider_secrets


def test_load_provider_secrets_allowlists_keys_and_does_not_execute(tmp_path, monkeypatch):
    path = tmp_path / "provider.env"
    path.write_text(
        "# comments are allowed\n"
        "TIINGO_API_KEY='tiingo-test'\n"
        "MASSIVE_API_KEY=massive-test\n"
        "UNSAFE=$(touch SHOULD_NOT_EXIST)\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    loaded = load_provider_secrets(path)

    assert loaded == ("TIINGO_API_KEY", "MASSIVE_API_KEY")
    assert os.environ["TIINGO_API_KEY"] == "tiingo-test"
    assert os.environ["MASSIVE_API_KEY"] == "massive-test"
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert "UNSAFE" not in os.environ


def test_explicit_environment_wins_and_insecure_file_is_ignored(tmp_path, monkeypatch):
    path = tmp_path / "provider.env"
    path.write_text("TIINGO_API_KEY=file-value\n", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.setenv("TIINGO_API_KEY", "explicit-value")

    assert load_provider_secrets(path) == ()
    assert os.environ["TIINGO_API_KEY"] == "explicit-value"
