"""Load optional provider credentials for the scheduled runtime.

The launchd process does not inherit an interactive shell's environment.  This
module provides a small, non-shell-parsing bridge for local provider secrets so
the scheduled path can use authenticated providers without putting credentials
in the repository or in a launchd plist committed to source control.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SECRET_FILE = Path("~/.config/system/provider.env").expanduser()
ALLOWED_PROVIDER_KEYS = frozenset(
    {
        "FRED_API_KEY",
        "OPENBB_FRED_API_KEY",
        "TIINGO_API_KEY",
        "MASSIVE_API_KEY",
    }
)


def _secret_file_path(path: str | os.PathLike[str] | None = None) -> Path:
    configured = path if path is not None else os.environ.get("SYSTEM_PROVIDER_SECRETS_FILE", "")
    return Path(configured).expanduser() if configured else DEFAULT_SECRET_FILE


def _secure_file(path: Path) -> bool:
    """Require a user-owned file with no group/other permissions."""
    try:
        details = path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(details.st_mode):
        logger.warning("Provider secret file is not a regular file; ignoring %s", path)
        return False
    if details.st_uid != os.getuid():
        logger.warning("Provider secret file is not owned by the current user; ignoring %s", path)
        return False
    if details.st_mode & 0o077:
        logger.warning("Provider secret file must be mode 600 or stricter; ignoring %s", path)
        return False
    return True


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def _normalise_fred_key(file_values: dict[str, str], loaded: list[str]) -> None:
    """Expose exactly one logical FRED secret to downstream providers.

    ``OPENBB_FRED_API_KEY`` is accepted only as an input compatibility name.
    Once it crosses this boundary, provider/domain code receives the canonical
    ``FRED_API_KEY`` name and the compatibility alias is removed from the
    process environment.
    """
    canonical = os.environ.get("FRED_API_KEY", "").strip()
    if not canonical:
        canonical = os.environ.get("OPENBB_FRED_API_KEY", "").strip()
    if not canonical:
        canonical = file_values.get("FRED_API_KEY", "").strip()
    if not canonical:
        canonical = file_values.get("OPENBB_FRED_API_KEY", "").strip()
    if canonical and not os.environ.get("FRED_API_KEY", "").strip():
        os.environ["FRED_API_KEY"] = canonical
        loaded.append("FRED_API_KEY")
    os.environ.pop("OPENBB_FRED_API_KEY", None)


def load_provider_secrets(
    path: str | os.PathLike[str] | None = None,
) -> tuple[str, ...]:
    """Load allowed ``KEY=VALUE`` entries without executing the file.

    Existing non-empty environment variables win.  The return value contains
    only the names loaded, never secret values, which keeps callers and logs
    safe by construction.
    """
    loaded: list[str] = []
    file_values: dict[str, str] = {}
    # Normalize an explicitly supplied compatibility environment variable even
    # when the host secret file is absent or rejected.
    _normalise_fred_key(file_values, loaded)

    secret_path = _secret_file_path(path)
    if not secret_path.exists():
        return tuple(dict.fromkeys(loaded))
    if not _secure_file(secret_path):
        return tuple(dict.fromkeys(loaded))

    try:
        lines = secret_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Unable to read provider secret file %s", secret_path)
        return tuple(dict.fromkeys(loaded))

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            logger.warning("Ignoring malformed provider secret entry at %s:%d", secret_path, line_number)
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_PROVIDER_KEYS:
            logger.warning("Ignoring unsupported provider secret name %s", key)
            continue
        if key in {"FRED_API_KEY", "OPENBB_FRED_API_KEY"}:
            if key not in file_values and not os.environ.get(key, "").strip():
                value = _parse_value(raw_value)
                if value:
                    file_values[key] = value
            continue
        if os.environ.get(key, "").strip():
            continue
        value = _parse_value(raw_value)
        if not value:
            continue
        os.environ[key] = value
        loaded.append(key)
    _normalise_fred_key(file_values, loaded)
    return tuple(dict.fromkeys(loaded))
