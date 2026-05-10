from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKBENCH_SRC = ROOT / "Workbench" / "src"
if str(WORKBENCH_SRC) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_SRC))

from workbench.governance.config_audit import audit_config


def test_authority_config_enabled_emits_event(tmp_path) -> None:
    registry = tmp_path / "config_registry.yaml"
    registry.write_text(
        """
allow_legacy_fallback:
  type: AUTHORITY_CONFIG
  default_allowed: false
  severity: HIGH
  reason: "Bypasses admitted evidence path."
""",
        encoding="utf-8",
    )

    events = audit_config({"allow_legacy_fallback": True}, registry)

    assert len(events) == 1
    assert events[0]["event_type"] == "AUTHORITY_CONFIG_ENABLED"
    assert events[0]["decision_impact"] == "ACTION_REQUIRED"


def test_unknown_suspicious_authority_config_is_blocked(tmp_path) -> None:
    registry = tmp_path / "config_registry.yaml"
    registry.write_text("sigma_threshold:\n  type: PARAMETER_CONFIG\n", encoding="utf-8")

    events = audit_config({"bypass_promotion_gate": True}, registry)

    assert len(events) == 1
    assert events[0]["event_type"] == "UNKNOWN_AUTHORITY_CONFIG_ENABLED"
    assert events[0]["decision_impact"] == "BLOCK"
