from __future__ import annotations

from pathlib import Path
import re


VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL", "OK"}
VALID_VERDICTS = {
    "BLOCK",
    "PROMOTE",
    "DOWNWEIGHT",
    "QUARANTINE",
    "INVESTIGATE",
    "ACTION_REQUIRED",
    "DISPLAY_ONLY",
}
PLACEHOLDER_VALUES = {
    "",
    "...",
    "n/a",
    "na",
    "none",
    "null",
    "owner",
    "someone",
    "tbd",
    "todo",
    "unknown",
}


class ReportGateError(RuntimeError):
    """Raised when a governance report fails structural or content validation."""


def _field(text: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*(.+)", text)
    if not match:
        raise ReportGateError(f"Report missing {name} field")
    return match.group(1).strip().lstrip("- ").strip()


def _actionable_verdict_section(text: str) -> str:
    marker = "## Actionable Verdict"
    if marker not in text:
        raise ReportGateError("Report missing Actionable Verdict")
    section = text.split(marker, 1)[1]
    next_section = section.find("\n## ")
    if next_section >= 0:
        section = section[:next_section]
    return section


def _reject_placeholder(field: str, value: str) -> None:
    normalized = value.strip().lower()
    if normalized in PLACEHOLDER_VALUES:
        raise ReportGateError(f"Report has placeholder {field}: {value!r}")


def validate_report_verdict(report_path: str | Path) -> dict[str, str]:
    """Validate that a governance report has a well-formed Actionable Verdict.

    Veto check — raises ReportGateError if the report is malformed, has
    placeholder values, invalid verdict/severity, or violates severity-verdict
    constraints (e.g. HIGH severity cannot be DISPLAY_ONLY).  Does not grant
    authority; only confirms the report meets structural requirements.
    """
    report_path = Path(report_path)
    text = report_path.read_text(encoding="utf-8")
    section = _actionable_verdict_section(text)
    verdict = _field(section, "Verdict")
    if verdict not in VALID_VERDICTS:
        raise ReportGateError(f"Invalid verdict {verdict} in {report_path}")
    severity = _field(section, "Severity") if "Severity:" in section else "UNKNOWN"
    if severity not in VALID_SEVERITIES:
        raise ReportGateError(f"Invalid severity {severity} in {report_path}")
    required_action = _field(section, "Required Action")
    owner = _field(section, "Owner")
    _reject_placeholder("Required Action", required_action)
    _reject_placeholder("Owner", owner)
    if verdict in {"BLOCK", "DOWNWEIGHT", "QUARANTINE", "ACTION_REQUIRED", "INVESTIGATE"}:
        if len(required_action.split()) < 3:
            raise ReportGateError(f"Report Required Action is too vague: {report_path}")
    if severity in {"HIGH", "CRITICAL"} and verdict == "DISPLAY_ONLY":
        raise ReportGateError(f"High-severity report cannot be DISPLAY_ONLY: {report_path}")
    return {
        "report_path": str(report_path),
        "verdict": verdict,
        "severity": severity,
        "owner": owner,
        "required_action": required_action,
    }
