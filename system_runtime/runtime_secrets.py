"""Load optional runtime sink credentials without executing a shell file.

The scheduled macOS jobs do not inherit the interactive shell environment.
Runtime sink credentials therefore live in a user-owned mode-600 file and are
loaded by the launchd wrapper immediately before the real process starts.

Only the small allowlist below is accepted.  Existing non-empty environment
variables remain authoritative, which keeps CI/operator overrides explicit.
"""
from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_SECRET_FILE = Path("~/.config/system/observability.env").expanduser()
ALLOWED_RUNTIME_KEYS = frozenset(
    {
        "SENTRY_DSN",
        "SENTRY_ENVIRONMENT",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "FEISHU_WEBHOOK_URL",
        "HEALTHCHECKS_DAILY_RUN_URL",
    }
)


def _secret_file_path(path: str | os.PathLike[str] | None = None) -> Path:
    configured = (
        path
        if path is not None
        else os.environ.get("SYSTEM_OBSERVABILITY_SECRETS_FILE", "")
    )
    return Path(configured).expanduser() if configured else DEFAULT_SECRET_FILE


def _secure_file(path: Path) -> bool:
    """Require a regular, current-user-owned file with no group/other bits."""
    try:
        details = path.stat()
    except OSError:
        return False
    if not stat.S_ISREG(details.st_mode):
        logger.warning("Runtime secret file is not a regular file; ignoring it")
        return False
    if details.st_uid != os.getuid():
        logger.warning("Runtime secret file is not owned by the current user; ignoring it")
        return False
    if details.st_mode & 0o077:
        logger.warning("Runtime secret file must be mode 600 or stricter; ignoring it")
        return False
    return True


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def load_runtime_secrets(
    path: str | os.PathLike[str] | None = None,
) -> tuple[str, ...]:
    """Load allowlisted ``KEY=VALUE`` entries without executing the file.

    The return value contains names only, never secret values, so callers can
    safely include it in diagnostics.
    """
    secret_path = _secret_file_path(path)
    if not secret_path.exists() or not _secure_file(secret_path):
        return ()
    try:
        lines = secret_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Unable to read runtime secret file")
        return ()

    loaded: list[str] = []
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            logger.warning("Ignoring malformed runtime secret entry at line %d", line_number)
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in ALLOWED_RUNTIME_KEYS:
            logger.warning("Ignoring unsupported runtime secret name %s", key)
            continue
        if os.environ.get(key, "").strip():
            continue
        value = _parse_value(raw_value)
        if not value:
            continue
        os.environ[key] = value
        loaded.append(key)
    return tuple(loaded)


__all__ = ["ALLOWED_RUNTIME_KEYS", "DEFAULT_SECRET_FILE", "load_runtime_secrets"]
