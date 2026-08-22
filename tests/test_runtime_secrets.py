from __future__ import annotations

import os
from pathlib import Path

from system_runtime.runtime_secrets import load_runtime_secrets


def test_runtime_secrets_allowlist_requires_mode_600_and_does_not_execute(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "observability.env"
    path.write_text(
        "SENTRY_DSN=https://example.invalid/1\n"
        "FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/test\n"
        "UNSAFE=$(touch /tmp/should-not-exist)\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    for key in ("SENTRY_DSN", "FEISHU_WEBHOOK_URL"):
        monkeypatch.delenv(key, raising=False)

    loaded = load_runtime_secrets(path)

    assert loaded == ("SENTRY_DSN", "FEISHU_WEBHOOK_URL")
    assert os.environ["SENTRY_DSN"] == "https://example.invalid/1"
    assert "UNSAFE" not in os.environ


def test_runtime_secrets_rejects_group_readable_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "observability.env"
    path.write_text("SENTRY_DSN=https://example.invalid/1\n", encoding="utf-8")
    path.chmod(0o644)
    monkeypatch.delenv("SENTRY_DSN", raising=False)

    assert load_runtime_secrets(path) == ()
    assert "SENTRY_DSN" not in os.environ
