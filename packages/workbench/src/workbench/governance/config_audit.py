from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


SUSPICIOUS_AUTHORITY_TERMS = (
    "allow_",
    "bypass",
    "disable",
    "force",
    "legacy",
    "promote",
    "skip",
)


def audit_config(config: dict[str, Any], registry_path: str | Path) -> list[dict[str, Any]]:
    """Audit config dict against the authority registry.

    Returns a list of audit events for suspicious or authority-bearing config
    keys.  Unregistered keys with authority-like names produce HIGH severity
    UNKNOWN_AUTHORITY_CONFIG_ENABLED events.  Registered AUTHORITY_CONFIG keys
    that are enabled when default_allowed=False produce ACTION_REQUIRED events.
    """
    registry = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8")) or {}
    events: list[dict[str, Any]] = []
    for key, value in config.items():
        rule = registry.get(key)
        if not rule:
            if bool(value) is True and any(term in key.lower() for term in SUSPICIOUS_AUTHORITY_TERMS):
                events.append(
                    {
                        "config_key": key,
                        "value": value,
                        "event_type": "UNKNOWN_AUTHORITY_CONFIG_ENABLED",
                        "severity": "HIGH",
                        "reason": "Enabled config key looks authority-bearing but is absent from registry.",
                        "decision_impact": "BLOCK",
                    }
                )
            continue
        if rule.get("type") != "AUTHORITY_CONFIG":
            continue
        default_allowed = rule.get("default_allowed", False)
        if bool(value) is True and default_allowed is False:
            events.append(
                {
                    "config_key": key,
                    "value": value,
                    "event_type": "AUTHORITY_CONFIG_ENABLED",
                    "severity": rule.get("severity", "HIGH"),
                    "reason": rule.get("reason", ""),
                    "decision_impact": "ACTION_REQUIRED",
                }
            )
    return events
