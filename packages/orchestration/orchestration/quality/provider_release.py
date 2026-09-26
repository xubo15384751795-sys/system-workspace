"""Provider release and causal availability evaluator.

Content clocks answer when an observation was recorded.  This module answers
whether that observation was available to the decision at ``decision_time``.
It deliberately does not infer publication schedules from retrieval time or
from a provider's name.  Missing calendar or availability evidence blocks.
"""
from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from system_runtime.context import RuntimeContext
from system_runtime.provider_status import (
    PROVIDER_STATUSES,
    ProviderStatusPolicyError,
    validate_provider_status_matrix,
)
from orchestration.quality.provider_release_calendar import (
    evaluate_provider_release_calendar,
)

POLICY_RELATIVE_PATH = Path("configs/provider_release_policy.yaml")

_VALID_CALENDAR_STATUS = {"configured", "unconfigured"}
_VALID_RELEASE_EXPECTATIONS = {"scheduled", "no_scheduled_release"}
_VALID_OBSERVATION_FREQUENCIES = {
    "daily",
    "weekly",
    "monthly",
    "quarterly",
    "annual",
    "intraday",
    "irregular",
    "mixed",
}
_ISO_DURATION_RE = re.compile(
    r"^P(?:\d+D|T(?=\d)(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)$"
)
_VALID_PROVIDER_STATUSES = set(PROVIDER_STATUSES)
_VALID_DATA_CONTRACT_MODES = {"shadow", "enforce"}


class ProviderReleasePolicyError(ValueError):
    """Raised when a provider release policy is malformed."""


def load_provider_release_policy(root: Path | None = None) -> dict[str, Any]:
    """Load and validate the versioned provider release policy."""
    root = root or RuntimeContext.current_context().workspace
    path = root / POLICY_RELATIVE_PATH
    if not path.is_file():
        raise ProviderReleasePolicyError(f"provider release policy missing: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ProviderReleasePolicyError(f"provider release policy is invalid YAML: {path}") from exc
    validate_provider_release_policy(payload)
    return payload


def validate_provider_release_policy(payload: dict[str, Any]) -> None:
    """Validate policy structure without claiming that schedules are known."""
    if not isinstance(payload, dict):
        raise ProviderReleasePolicyError("provider release policy must be a mapping")
    if payload.get("schema_version") != "workbench.provider_release_policy.v1":
        raise ProviderReleasePolicyError("unsupported provider release policy schema")
    data_contract_mode = str(payload.get("data_contract_mode", "enforce")).strip().lower()
    if data_contract_mode not in _VALID_DATA_CONTRACT_MODES:
        raise ProviderReleasePolicyError(
            "provider release policy data_contract_mode must be shadow or enforce"
        )
    rules = payload.get("rules")
    if not isinstance(rules, list) or not rules:
        raise ProviderReleasePolicyError("provider release policy requires non-empty rules")
    status_matrix = payload.get("status_matrix")
    if not isinstance(status_matrix, dict):
        raise ProviderReleasePolicyError("provider release policy requires status_matrix")
    try:
        validate_provider_status_matrix(status_matrix)
    except ProviderStatusPolicyError as exc:
        message = str(exc).replace(
            "provider status matrix",
            "provider release policy status_matrix",
        )
        raise ProviderReleasePolicyError(message) from exc
    seen: set[str] = set()
    required = {
        "rule_id",
        "provider_id",
        "series_id",
        "dataset_id",
        "observation_frequency",
        "calendar_status",
        "release_expectation",
        "release_timezone",
        "release_cutoff_local",
        "nominal_publication_lag",
        "business_calendar_basis",
        "revision_vintage_policy",
        "deletion_correction_policy",
        "reuse_policy",
        "rule_version",
        "owner",
        "official_evidence_url",
    }
    for rule in rules:
        if not isinstance(rule, dict):
            raise ProviderReleasePolicyError("provider release policy rules must be mappings")
        missing = sorted(required - set(rule))
        if missing:
            raise ProviderReleasePolicyError(
                f"provider release policy rule missing fields: {missing}"
            )
        rule_id = str(rule["rule_id"])
        if not rule_id or rule_id in seen:
            raise ProviderReleasePolicyError(f"duplicate or empty provider release rule_id: {rule_id!r}")
        seen.add(rule_id)
        if rule["calendar_status"] not in _VALID_CALENDAR_STATUS:
            raise ProviderReleasePolicyError(
                f"unsupported calendar_status for {rule_id}: {rule['calendar_status']!r}"
            )
        if rule["release_expectation"] not in _VALID_RELEASE_EXPECTATIONS:
            raise ProviderReleasePolicyError(
                f"unsupported release_expectation for {rule_id}: "
                f"{rule['release_expectation']!r}"
            )
        if not str(rule["provider_id"]).strip() or not str(rule["dataset_id"]).strip():
            raise ProviderReleasePolicyError(f"provider and dataset IDs are required: {rule_id}")
        if rule["observation_frequency"] not in _VALID_OBSERVATION_FREQUENCIES:
            raise ProviderReleasePolicyError(
                f"unsupported observation_frequency for {rule_id}: "
                f"{rule['observation_frequency']!r}"
            )
        if not str(rule["official_evidence_url"]).strip():
            raise ProviderReleasePolicyError(f"official evidence URL is required: {rule_id}")
        if rule["calendar_status"] == "configured":
            if rule["release_expectation"] == "scheduled":
                configured_fields = (
                    "release_timezone",
                    "release_cutoff_local",
                    "nominal_publication_lag",
                )
                if any(rule[field] in (None, "", "unknown") for field in configured_fields):
                    raise ProviderReleasePolicyError(
                        f"configured rule has unknown release calendar fields: {rule_id}"
                    )
                try:
                    ZoneInfo(str(rule["release_timezone"]))
                except (ZoneInfoNotFoundError, ValueError) as exc:
                    raise ProviderReleasePolicyError(
                        f"configured rule has invalid release timezone: {rule_id}"
                    ) from exc
                try:
                    datetime.strptime(str(rule["release_cutoff_local"]), "%H:%M")
                except ValueError as exc:
                    raise ProviderReleasePolicyError(
                        f"configured rule has invalid release cutoff: {rule_id}"
                    ) from exc
                if _ISO_DURATION_RE.fullmatch(str(rule["nominal_publication_lag"])) is None:
                    raise ProviderReleasePolicyError(
                        f"configured rule has invalid nominal publication lag: {rule_id}"
                    )
                if str(rule["business_calendar_basis"]).strip().lower() in {"", "unknown"}:
                    raise ProviderReleasePolicyError(
                        f"configured rule has unknown business calendar: {rule_id}"
                    )


def resolve_provider_release_rule(
    provider_id: str,
    *,
    series_id: str = "",
    dataset_id: str = "",
    policy: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Resolve the most specific provider/series/dataset rule."""
    root = root or RuntimeContext.current_context().workspace
    payload = policy or load_provider_release_policy(root)
    validate_provider_release_policy(payload)
    candidates = [
        rule
        for rule in payload["rules"]
        if rule["provider_id"] == provider_id
        and rule["dataset_id"] in {dataset_id, "*"}
        and rule["series_id"] in {series_id, "*"}
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda rule: (
            rule["dataset_id"] != "*",
            rule["series_id"] != "*",
        ),
        reverse=True,
    )
    return dict(candidates[0])


def evaluate_provider_availability(
    event: dict[str, Any],
    *,
    decision_time: datetime,
    policy: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate whether one provider event is causally usable.

    ``available_at`` is mandatory for every status except a proven
    ``no_release_expected`` event.  ``retrieved_at`` is retained as audit
    metadata and is never used as a substitute for publication availability.
    """
    root = root or RuntimeContext.current_context().workspace
    provider = str(event.get("provider_id") or event.get("provider") or "")
    series_id = str(event.get("series_id") or "")
    dataset_id = str(event.get("dataset_id") or "")
    provider_status = str(event.get("status") or "unknown")
    result: dict[str, Any] = {
        "schema_version": "provider_availability_result.v1",
        "evaluator": "orchestration.quality.provider_release",
        "provider_id": provider,
        "series_id": series_id,
        "dataset_id": dataset_id,
        "provider_status": provider_status,
        "decision_time": _timestamp(decision_time),
        "observation_date": event.get("observation_date"),
        "available_at": event.get("available_at"),
        "retrieved_at": event.get("retrieved_at"),
        "revision": event.get("revision"),
        "vintage_date": event.get("vintage_date"),
        "policy_rule_id": None,
        "policy_version": None,
        "verdict": "BLOCKED",
        "reason_code": "UNKNOWN_PROVIDER_OUTCOME",
        "errors": [],
    }
    # The publication calendar is a shadow schedule oracle.  Keep its
    # expected clock attached to the evaluator result, but never copy it into
    # event["available_at"]: the provider must still evidence causal
    # availability explicitly before this evaluator can PASS.
    result["release_calendar"] = evaluate_provider_release_calendar(
        {
            "provider_id": provider,
            "series_id": series_id,
            "dataset_id": dataset_id,
            "observation_date": event.get("observation_date"),
        },
        decision_time=decision_time,
        root=root,
    )
    if provider_status not in _VALID_PROVIDER_STATUSES:
        result["errors"].append("unknown_provider_status")
        return result

    policy_payload = policy or load_provider_release_policy(root)
    validate_provider_release_policy(policy_payload)
    rule = resolve_provider_release_rule(
        provider,
        series_id=series_id,
        dataset_id=dataset_id,
        policy=policy_payload,
        root=root,
    )
    if rule is None:
        result["reason_code"] = "MISSING_PROVIDER_RELEASE_POLICY"
        result["errors"].append("no_matching_release_policy")
        return result
    result["policy_rule_id"] = rule["rule_id"]
    result["policy_version"] = rule["rule_version"]
    result["observation_frequency"] = rule["observation_frequency"]
    result["status_policy"] = dict(policy_payload["status_matrix"][provider_status])
    route_policy = event.get("route_policy")
    if isinstance(route_policy, dict):
        result["route_policy"] = dict(route_policy)
        if bool(route_policy.get("diagnostic_only")):
            result["verdict"] = "WARN"
            result["reason_code"] = "DIAGNOSTIC_ONLY_PROVIDER_ROUTE"
            result["errors"].append("selected_provider_route_is_diagnostic_only")
            return result
    if provider_status == "environmentally_blocked":
        result["verdict"] = "WARN"
        result["reason_code"] = "ENVIRONMENTALLY_BLOCKED"
        result["errors"].append("provider_unavailable_from_declared_environment")
        return result
    if rule["calendar_status"] != "configured":
        result["reason_code"] = "PROVIDER_RELEASE_CALENDAR_UNCONFIGURED"
        result["errors"].append("release_timezone_cutoff_lag_not_evidenced")
        return result

    if provider_status == "provider_failed_no_acceptable_fallback":
        result["verdict"] = "FAIL"
        result["reason_code"] = "PROVIDER_FAILED_NO_ACCEPTABLE_FALLBACK"
        return result
    if provider_status == "reused_after_provider_failure":
        result["reason_code"] = "REUSED_AFTER_PROVIDER_FAILURE"
        return result

    observation_date = _parse_date(event.get("observation_date"))
    available_at = _parse_timestamp(event.get("available_at"))
    retrieved_at = _parse_timestamp(event.get("retrieved_at"))
    vintage_date = _parse_date(event.get("vintage_date"))
    revision = event.get("revision")
    parsed_decision_time = _parse_timestamp(decision_time)
    if parsed_decision_time is None:
        result["errors"].append("invalid_decision_time")
        result["reason_code"] = "MISSING_CAUSAL_AVAILABILITY_EVIDENCE"
        return result
    if observation_date is None:
        result["errors"].append("missing_observation_date")
    if retrieved_at is None:
        result["errors"].append("missing_retrieved_at")
    if provider_status != "no_release_expected" and available_at is None:
        result["errors"].append("missing_available_at")
    if rule.get("revision_vintage_policy") == "explicit_vintage":
        if vintage_date is None:
            result["errors"].append("missing_vintage_date")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            result["errors"].append("invalid_revision")
    if (
        observation_date is not None
        and vintage_date is not None
        and vintage_date < observation_date
    ):
        result["errors"].append("vintage_before_observation")
    if result["errors"]:
        result["reason_code"] = "MISSING_CAUSAL_AVAILABILITY_EVIDENCE"
        return result
    if observation_date and observation_date > parsed_decision_time.date():
        result["errors"].append("observation_after_decision")
    if available_at and available_at > parsed_decision_time:
        result["errors"].append("available_after_decision")
    if available_at and retrieved_at and retrieved_at < available_at:
        result["errors"].append("retrieved_before_available")
    if result["errors"]:
        result["reason_code"] = "CAUSAL_AVAILABILITY_VIOLATION"
        return result

    if provider_status == "no_release_expected":
        if rule.get("release_expectation") != "no_scheduled_release":
            result["reason_code"] = "NO_RELEASE_POLICY_NOT_PROVEN"
            return result
        result["verdict"] = "PASS"
        result["reason_code"] = "NO_RELEASE_EXPECTED"
        return result
    if provider_status in {"partial_provider_success", "reused_same_content"}:
        if rule.get("reuse_policy") != "warn_allowed":
            result["reason_code"] = "DEGRADED_PROVIDER_OUTCOME"
            return result
        result["verdict"] = "WARN"
        result["reason_code"] = "DEGRADED_PROVIDER_OUTCOME"
        return result
    if provider_status == "refreshed":
        result["verdict"] = "PASS"
        result["reason_code"] = "PROVIDER_AVAILABLE_BEFORE_DECISION"
        return result

    result["reason_code"] = "UNSUPPORTED_PROVIDER_STATUS"
    return result


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _timestamp(value: datetime) -> str:
    parsed = _parse_timestamp(value)
    if parsed is None:
        raise ProviderReleasePolicyError("decision_time must be timezone-aware")
    return parsed.isoformat().replace("+00:00", "Z")


__all__ = [
    "ProviderReleasePolicyError",
    "evaluate_provider_availability",
    "load_provider_release_policy",
    "resolve_provider_release_rule",
    "validate_provider_release_policy",
]
