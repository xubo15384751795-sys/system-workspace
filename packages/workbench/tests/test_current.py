"""Tests for workbench.current — pure parsing and rendering logic."""
from __future__ import annotations

import workbench.current as current


# ---------------------------------------------------------------------------
# extract_main_signal
# ---------------------------------------------------------------------------

SIGNAL_MD = """\
# Executive Summary

Some intro text.

## Main Signal
- Morphology: compression_fold
- Sigma: 2.341
- Singular regime: yes
- Leading channel: M

## Next Section
Other content.
"""

NO_SIGNAL_MD = """\
## Framework Output

Nothing here.
"""

EMPTY_SIGNAL_MD = """\
## Main Signal

## Other
"""


class TestExtractMainSignal:
    def test_extracts_bullet_lines(self):
        lines = current.extract_main_signal(SIGNAL_MD)
        assert any("Morphology" in line for line in lines)
        assert any("Sigma" in line for line in lines)

    def test_stops_at_next_heading(self):
        lines = current.extract_main_signal(SIGNAL_MD)
        assert not any("Next Section" in line for line in lines)
        assert not any("Other content" in line for line in lines)

    def test_missing_section_returns_fallback(self):
        lines = current.extract_main_signal(NO_SIGNAL_MD)
        assert lines == ["- Main signal not found in latest summary."]

    def test_empty_section_returns_fallback(self):
        lines = current.extract_main_signal(EMPTY_SIGNAL_MD)
        assert lines == ["- Main signal block is empty."]

    def test_custom_heading(self):
        md = "## Custom Heading\n- Key: value\n\n## Other"
        lines = current.extract_main_signal(md, heading="## Custom Heading")
        assert any("Key" in line for line in lines)

    def test_custom_heading_not_found(self):
        md = "## Main Signal\n- Key: value"
        lines = current.extract_main_signal(md, heading="## Missing Heading")
        assert lines == ["- Main signal not found in latest summary."]


# ---------------------------------------------------------------------------
# extract_top_actions
# ---------------------------------------------------------------------------

def _queue_row(row_id, date, action, extra=""):
    mid = ["x"] * 7
    return "| " + " | ".join([row_id, date, *mid, action, extra]) + " |"


QUEUE_MD = "\n".join([
    "| id | date | x | y | z | a | b | c | d | Proposed Action | extra |",
    "|---|---|---|---|---|---|---|---|---|---|---|",
    _queue_row("1", "2026-05-01", "Fix the thing"),
    _queue_row("2", "2026-05-02", "Check rate vol"),
    _queue_row("3", "2026-05-03", "Promote snapshot"),
    _queue_row("4", "2026-05-04", "Fourth action"),
])


class TestExtractTopActions:
    def test_returns_default_three(self):
        actions = current.extract_top_actions(QUEUE_MD)
        assert len(actions) == 3

    def test_first_action_correct(self):
        actions = current.extract_top_actions(QUEUE_MD)
        assert actions[0] == "Fix the thing"

    def test_custom_limit(self):
        actions = current.extract_top_actions(QUEUE_MD, limit=2)
        assert len(actions) == 2

    def test_empty_input_returns_fallback(self):
        actions = current.extract_top_actions("")
        assert actions == ["No proposed next actions found."]

    def test_header_row_skipped(self):
        actions = current.extract_top_actions(QUEUE_MD)
        assert all("Proposed Action" not in a for a in actions)


# ---------------------------------------------------------------------------
# _signal_payload
# ---------------------------------------------------------------------------

class TestSignalPayload:
    def test_parses_key_value_lines(self):
        lines = ["- Morphology: compression_fold", "- Sigma: 2.341", "- Leading channel: M"]
        payload = current._signal_payload(lines)
        assert payload["morphology"] == "compression_fold"
        assert payload["sigma"] == "2.341"
        assert payload["leading_channel"] == "M"

    def test_spaces_in_key_become_underscores(self):
        payload = current._signal_payload(["- Leading channel: M"])
        assert "leading_channel" in payload

    def test_non_matching_lines_skipped(self):
        payload = current._signal_payload(["no colon here", "- good: val"])
        assert list(payload.keys()) == ["good"]

    def test_empty_input(self):
        assert current._signal_payload([]) == {}


# ---------------------------------------------------------------------------
# _compute_basic_from_advanced
# ---------------------------------------------------------------------------

SDF_CONTRACT = {
    "capabilities": [
        {"id": "sigma", "label": "Sigma", "value_path": "advanced.sigma", "render": "gauge"},
        {"id": "morphology", "label": "Morphology", "value_path": "advanced.morphology", "render": "label"},
        {"id": "singular_flag", "label": "Singular", "value_path": "advanced.singular_flag", "render": "alert"},
        {"id": "escalation", "label": "Escalation", "value_path": "advanced.escalation", "render": "alert"},
        {"id": "leading_channel", "label": "Channel", "value_path": "advanced.leading_channel", "render": "label"},
    ],
    "display": {
        "advanced_sections": [
            {"title": "Sigma_t", "from": "advanced.sigma", "format": "Sigma_t = {value}"},
            {"title": "Morphology", "from": "advanced.morphology", "format": "{value}"},
        ]
    },
}

MACRO_ENTRY = {"framework_id": "macro_pressure_measurement", "contract": SDF_CONTRACT}


class TestComputeBasicFromAdvanced:
    def _advanced(self, singular="no", escalation="no", leading_channel="unknown"):
        return {
            "morphology": "fold",
            "sigma": "1.200",
            "singular_regime": singular,
            "singular_flag": singular,
            "escalation": escalation,
            "escalation_flag": escalation,
            "leading_channel": leading_channel,
        }

    def test_singular_yes_is_alert(self):
        result = current._compute_basic_from_advanced(
            self._advanced(singular="yes"), SDF_CONTRACT, MACRO_ENTRY
        )
        assert result["overall"] == "ALERT"

    def test_escalation_true_is_alert(self):
        result = current._compute_basic_from_advanced(
            self._advanced(escalation="true"), SDF_CONTRACT, MACRO_ENTRY
        )
        assert result["overall"] == "ALERT"

    def test_leading_channel_is_watch(self):
        result = current._compute_basic_from_advanced(
            self._advanced(leading_channel="M"), SDF_CONTRACT, MACRO_ENTRY
        )
        assert result["overall"] == "WATCH"

    def test_clean_is_ok(self):
        result = current._compute_basic_from_advanced(
            self._advanced(), SDF_CONTRACT, MACRO_ENTRY
        )
        assert result["overall"] == "OK"

    def test_result_has_required_keys(self):
        result = current._compute_basic_from_advanced(
            self._advanced(), SDF_CONTRACT, MACRO_ENTRY
        )
        for key in ("overall", "main_pressure", "confidence", "summary"):
            assert key in result


# ---------------------------------------------------------------------------
# _format_float
# ---------------------------------------------------------------------------

class TestFormatFloat:
    def test_formats_to_three_decimals(self):
        assert current._format_float(1.23456) == "1.235"

    def test_none_returns_unknown(self):
        assert current._format_float(None) == "unknown"

    def test_string_number(self):
        assert current._format_float("2.5") == "2.500"

    def test_non_numeric_string_returns_unknown(self):
        assert current._format_float("abc") == "unknown"


# ---------------------------------------------------------------------------
# _yes_no
# ---------------------------------------------------------------------------

class TestYesNo:
    def test_true_returns_yes(self):
        assert current._yes_no(True) == "yes"

    def test_false_returns_no(self):
        assert current._yes_no(False) == "no"

    def test_none_returns_unknown(self):
        assert current._yes_no(None) == "unknown"

    def test_string_passed_through(self):
        assert current._yes_no("maybe") == "maybe"


# ---------------------------------------------------------------------------
# _resolve_channel_label
# ---------------------------------------------------------------------------

class TestResolveChannelLabel:
    def test_known_channels(self):
        assert "rates" in current._resolve_channel_label("M", MACRO_ENTRY).lower()
        assert "degrees" in current._resolve_channel_label("D", MACRO_ENTRY).lower()
        assert "curvature" in current._resolve_channel_label("K", MACRO_ENTRY).lower()
        assert "shadow" in current._resolve_channel_label("X", MACRO_ENTRY).lower()

    def test_unknown_channel(self):
        assert current._resolve_channel_label("Z", MACRO_ENTRY) == "Z"

    def test_none_returns_unknown(self):
        assert current._resolve_channel_label(None, MACRO_ENTRY) == "unknown"

    def test_unknown_string_returns_unknown(self):
        assert current._resolve_channel_label("unknown", MACRO_ENTRY) == "unknown"


# ---------------------------------------------------------------------------
# _extract_advanced_from_main_signal
# ---------------------------------------------------------------------------

class TestExtractAdvancedFromMainSignal:
    def test_extracts_from_main_signal_payload(self):
        main_signal = [
            "- Morphology: compression_fold",
            "- Sigma: 2.341",
            "- Singular regime: yes",
            "- Leading channel: M",
        ]
        advanced = current._extract_advanced_from_main_signal(main_signal, {}, SDF_CONTRACT)
        assert advanced.get("morphology") == "compression_fold"
        assert advanced.get("sigma") is not None
        # Value stored under capability ID (singular_flag), not payload key (singular_regime)
        assert advanced.get("singular_flag") == "yes"

    def test_falls_back_to_dashboard_state(self):
        main_signal: list[str] = []
        dashboard = {"snapshot_core": {"state": {"pattern": "STABLE_LOCAL", "sigma_t": 0.473, "singular_flag": False, "leading_channel": "D"}}}
        advanced = current._extract_advanced_from_main_signal(main_signal, dashboard, SDF_CONTRACT)
        assert advanced.get("morphology") == "STABLE_LOCAL"
        assert advanced.get("singular_flag") is False
        assert advanced.get("leading_channel") == "D"

    def test_main_signal_overrides_dashboard(self):
        main_signal = ["- Morphology: explicit_fold"]
        dashboard = {"snapshot_core": {"state": {"pattern": "STABLE_LOCAL"}}}
        advanced = current._extract_advanced_from_main_signal(main_signal, dashboard, SDF_CONTRACT)
        assert advanced.get("morphology") == "explicit_fold"


# ---------------------------------------------------------------------------
# refresh_current / live current card must not open deformation_runs/latest
# ---------------------------------------------------------------------------

def _write_neutral_snapshot(root) -> None:
    import json

    current_dir = root / "Output" / "current"
    current_dir.mkdir(parents=True, exist_ok=True)
    (current_dir / "neutral_pressure_snapshot.json").write_text(
        json.dumps(
            {
                "schema_version": "neutral_pressure.snapshot.v1",
                "framework_id": "macro_pressure_measurement",
                "run_id": "neutral_live",
                "as_of": "2026-09-05",
                "status": "active_partial",
                "basic": {"overall": "WATCH", "main_pressure": "funding", "confidence": "bounded", "summary": "neutral"},
                "advanced": {"harvester_release": "rel-live"},
            }
        )
        + "\n",
        encoding="utf-8",
    )


class TestRefreshCurrentSkipsArchivedDeformation:
    def test_macro_pressure_only_does_not_open_deformation_latest(self, tmp_path):
        trap = tmp_path / "Output" / "deformation_runs" / "latest"
        trap.mkdir(parents=True)
        (trap / "run_manifest.json").write_text(
            '{"run_id": "TRAP", "harvester_release": "TRAP"}\n', encoding="utf-8"
        )
        _write_neutral_snapshot(tmp_path)

        current.refresh_current()

        readme = (tmp_path / "Output" / "current" / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
        assert "TRAP" not in readme
        model_run = tmp_path / "Output" / "current" / "model_run_macro_pressure_measurement.json"
        assert model_run.exists()
        assert not (tmp_path / "Output" / "current" / "model_run.json").exists()

    def test_empty_active_registry_does_not_open_deformation_latest(self, tmp_path, monkeypatch):
        trap = tmp_path / "Output" / "deformation_runs" / "latest"
        trap.mkdir(parents=True)
        (trap / "run_manifest.json").write_text(
            '{"run_id": "TRAP", "harvester_release": "TRAP"}\n', encoding="utf-8"
        )
        monkeypatch.setattr(current, "load_registry", lambda: {"frameworks": []})
        monkeypatch.setattr(current, "active_frameworks", lambda registry=None: [])

        current.refresh_current()

        readme = (tmp_path / "Output" / "current" / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
        assert "TRAP" not in readme
        assert "deformation_runs" not in readme

    def test_resolve_framework_output_root_has_no_deformation_fallback(self):
        root = current._resolve_framework_output_root({"framework_id": "macro_pressure_measurement", "contract": {}})
        assert root is None
