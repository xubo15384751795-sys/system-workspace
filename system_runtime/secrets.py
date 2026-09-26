"""Provider-neutral secret access for the application runtime.

The application and domain packages depend on :class:`SecretProvider`, not on
an operating-system-specific file, plist, or environment variable alias. A
host adapter may compose environment variables with a mode-600 file (or a
different implementation on Linux/systemd) without changing domain code.

This module deliberately never exposes secret values in representations,
diagnostics, or log messages.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Protocol


class SecretProvider(Protocol):
    """Minimal dependency required by provider/application code."""

    def get(self, name: str, default: str | None = None) -> str | None:
        """Return a secret value without revealing how the host stores it."""

    def has(self, name: str) -> bool:
        """Return whether a non-empty value is available."""


@dataclass(frozen=True)
class EnvironmentSecretProvider:
    """Read secrets from the process environment."""

    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def get(self, name: str, default: str | None = None) -> str | None:
        value = os.environ.get(name, "").strip()
        if value:
            return value
        for alias in self.aliases.get(name, ()):
            value = os.environ.get(alias, "").strip()
            if value:
                return value
        return default

    def has(self, name: str) -> bool:
        return bool(self.get(name))


@dataclass(frozen=True)
class Mode600FileSecretProvider:
    """Host implementation for a user-owned, mode-600 ``KEY=VALUE`` file.

    The path is resolved at the host boundary and is never imported by domain
    modules. ``allowed_names`` prevents an arbitrary environment file from
    becoming a secret registry.
    """

    path: Path
    allowed_names: frozenset[str] = frozenset()
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def _secure(self) -> bool:
        try:
            details = self.path.stat()
        except OSError:
            return False
        return (
            stat.S_ISREG(details.st_mode)
            and details.st_uid == os.getuid()
            and not details.st_mode & 0o077
        )

    def _values(self) -> dict[str, str]:
        if not self._secure():
            return {}
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        values: dict[str, str] = {}
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, raw_value = line.split("=", 1)
            key = key.strip()
            if self.allowed_names and key not in self.allowed_names:
                continue
            value = raw_value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            if value.strip():
                values[key] = value.strip()
        return values

    def get(self, name: str, default: str | None = None) -> str | None:
        values = self._values()
        value = values.get(name, "").strip()
        if value:
            return value
        for alias in self.aliases.get(name, ()):
            value = values.get(alias, "").strip()
            if value:
                return value
        return default

    def has(self, name: str) -> bool:
        return bool(self.get(name))


@dataclass(frozen=True)
class CompositeSecretProvider:
    """Resolve a logical secret from ordered host implementations."""

    providers: tuple[SecretProvider, ...]

    def get(self, name: str, default: str | None = None) -> str | None:
        for provider in self.providers:
            value = provider.get(name)
            if value:
                return value
        return default

    def has(self, name: str) -> bool:
        return bool(self.get(name))


FRED_SECRET_ALIASES = {"FRED_API_KEY": ("OPENBB_FRED_API_KEY",)}
PROVIDER_SECRET_NAMES = frozenset(
    {"FRED_API_KEY", "OPENBB_FRED_API_KEY", "TIINGO_API_KEY", "MASSIVE_API_KEY"}
)
RUNTIME_SECRET_NAMES = frozenset(
    {
        "SENTRY_DSN",
        "SENTRY_ENVIRONMENT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_HTTP_PROXY_URL",
        "FEISHU_WEBHOOK_URL",
        "HEALTHCHECKS_DAILY_RUN_URL",
    }
)


def default_secret_provider() -> SecretProvider:
    """Build the local host implementation without leaking its path to code.

    ``SYSTEM_PROVIDER_SECRETS_FILE`` and ``SYSTEM_OBSERVABILITY_SECRETS_FILE``
    are host adapter inputs. A Linux/systemd deployment can replace these
    providers in ``RuntimeContext`` without modifying Harvester/domain code.
    """

    provider_path = Path(
        os.environ.get("SYSTEM_PROVIDER_SECRETS_FILE", "~/.config/system/provider.env")
    ).expanduser()
    observability_path = Path(
        os.environ.get(
            "SYSTEM_OBSERVABILITY_SECRETS_FILE", "~/.config/system/observability.env"
        )
    ).expanduser()
    return CompositeSecretProvider(
        (
            EnvironmentSecretProvider(aliases=FRED_SECRET_ALIASES),
            Mode600FileSecretProvider(
                provider_path,
                allowed_names=PROVIDER_SECRET_NAMES,
                aliases=FRED_SECRET_ALIASES,
            ),
            Mode600FileSecretProvider(observability_path, allowed_names=RUNTIME_SECRET_NAMES),
        )
    )


__all__ = [
    "CompositeSecretProvider",
    "EnvironmentSecretProvider",
    "Mode600FileSecretProvider",
    "SecretProvider",
    "default_secret_provider",
]
