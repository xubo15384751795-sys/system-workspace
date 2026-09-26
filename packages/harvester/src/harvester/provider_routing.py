"""Provider routing helpers owned by the Harvester boundary."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from harvester.provider_catalog import (
    OFFICIAL_PROVIDER_OUTCOME_STATUSES,
    _EXTERNAL_MANAGED_PROVIDER_PRIORITIES,
)
from harvester.providers import openbb_available


def _is_external_managed_series(series: Any) -> bool:
    return bool(
        set(getattr(series, "provider_priority", ()) or ())
        & _EXTERNAL_MANAGED_PROVIDER_PRIORITIES
    )


def _external_indicator_timeout_seconds() -> int:
    """Return the bounded timeout for optional publisher feeds.

    These feeds are diagnostic/secondary inputs.  A stalled publisher must
    not consume the whole daily-run budget while the primary registry path is
    still able to produce a governed release candidate.
    """
    raw = os.environ.get("HARVESTER_EXTERNAL_TIMEOUT_SEC", "10").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 10
    return max(1, min(value, 30))

def _provider_outcome(
    *,
    status: str,
    provider: str,
    requested_count: int,
    succeeded_count: int,
    failed_series: list[str] | None = None,
    fallback_reason: str = "",
    error: str = "",
    providers_used: list[str] | None = None,
    series_providers: dict[str, str] | None = None,
    series_attempts: dict[str, Any] | None = None,
    series_source_signatures: dict[str, Any] | None = None,
    provider_chain: list[str] | None = None,
    fallback_used: bool = False,
    carry_forward_reason: str = "",
    deadline_skipped_series: list[str] | None = None,
) -> dict[str, Any]:
    """Build the shared, schema-constrained acquisition outcome payload."""
    if status not in OFFICIAL_PROVIDER_OUTCOME_STATUSES:
        raise ValueError(f"unsupported provider outcome status: {status}")
    failed = sorted(set(failed_series or []))
    outcome: dict[str, Any] = {
        "status": status,
        "provider": provider or "unknown",
        "requested_count": int(requested_count),
        "succeeded_count": int(succeeded_count),
        "failed_count": len(failed),
        "failed_series": failed,
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    if fallback_reason:
        outcome["fallback_reason"] = fallback_reason[:2000]
    if error:
        outcome["error"] = error[:2000]
    if providers_used:
        outcome["providers_used"] = sorted(set(str(item) for item in providers_used))
    if series_providers:
        outcome["series_providers"] = {
            str(key): str(value) for key, value in sorted(series_providers.items())
        }
    if series_attempts:
        outcome["series_attempts"] = {
            str(key): value for key, value in sorted(series_attempts.items())
        }
    if series_source_signatures:
        outcome["series_source_signatures"] = {
            str(key): value for key, value in sorted(series_source_signatures.items())
        }
    if provider_chain:
        outcome["provider_chain"] = [str(item) for item in provider_chain]
    if fallback_used:
        outcome["fallback_used"] = True
    if carry_forward_reason:
        outcome["carry_forward_reason"] = carry_forward_reason
    if deadline_skipped_series:
        outcome["deadline_skipped_series"] = sorted(set(str(item) for item in deadline_skipped_series))
    # ETF parity is a cross-asset panel concern.  The generic benchmark
    # outcome is intentionally mixed-source (FRED, H.4.1, Treasury, SEC,
    # external indicators, and sometimes Tiingo ETF rows); applying the ETF
    # route classifier to that whole outcome incorrectly turns a healthy
    # benchmark release into a diagnostic-only route.
    outcome["availability"] = {
        "state": "STALE"
        if status in {"reused_same_content", "reused_after_provider_failure", "environmentally_blocked"}
        else "UNKNOWN",
        "calendar_status": "UNCONFIGURED",
        "available_at": None,
        "retrieved_at": outcome["retrieved_at"],
        "decision_usable": False,
        "reason": "publication_calendar_or_available_at_not_evidenced",
    }
    return outcome


def _failed_attempt_failure_classes(provider_outcome: dict[str, Any] | None) -> list[str]:
    """Extract normalized failed-attempt categories for downstream gates."""
    if not isinstance(provider_outcome, dict):
        return []
    series_attempts = provider_outcome.get("series_attempts")
    if not isinstance(series_attempts, dict):
        return []
    categories: set[str] = set()
    for attempts in series_attempts.values():
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict) or attempt.get("outcome") == "success":
                continue
            category = attempt.get("failure_class")
            if category:
                categories.add(str(category))
    return sorted(categories)


def _merge_external_provider_outcome(
    provider_outcome: dict[str, Any] | None,
    *,
    requested_series: set[str],
    succeeded_series: dict[str, str],
    failed_series: dict[str, str],
    manual_series: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Fold the separately acquired external indicators into one outcome.

    ``stage_complete_release`` intentionally has two acquisition paths: the
    generic registry adapter and the public-file/API external-indicator
    provider.  The release artifacts still need one provider outcome, but the
    counts must not double-count the external series or leave their generic
    adapter misses behind as false failures.
    """
    if not requested_series and not manual_series:
        return provider_outcome

    base = dict(provider_outcome or {})
    base_failed = {str(item) for item in base.get("failed_series", [])}
    combined_failed = base_failed | {str(item) for item in failed_series}
    base_requested = int(base.get("requested_count", 0) or 0)
    base_succeeded = int(base.get("succeeded_count", 0) or 0)
    combined_requested = base_requested + len(requested_series)
    combined_succeeded = base_succeeded + len(succeeded_series)
    if combined_requested == 0:
        status = "no_release_expected"
    elif combined_failed and combined_succeeded == 0:
        status = "provider_failed_no_acceptable_fallback"
    elif combined_failed:
        status = "partial_provider_success"
    else:
        status = "refreshed"

    merged: dict[str, Any] = {
        **base,
        "status": status,
        "provider": "harvester.complete",
        "requested_count": combined_requested,
        "succeeded_count": combined_succeeded,
        "failed_count": len(combined_failed),
        "failed_series": sorted(combined_failed),
        "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    providers_used = {
        str(item) for item in (base.get("providers_used") or []) if str(item).strip()
    }
    providers_used.update(str(item) for item in succeeded_series.values() if str(item).strip())
    if providers_used:
        merged["providers_used"] = sorted(providers_used)

    series_providers = {
        str(key): str(value)
        for key, value in (base.get("series_providers") or {}).items()
    }
    series_providers.update(
        {str(key): str(value) for key, value in succeeded_series.items()}
    )
    if series_providers:
        merged["series_providers"] = dict(sorted(series_providers.items()))

    errors: list[str] = []
    existing_error = str(base.get("error") or "").strip()
    if existing_error:
        errors.append(existing_error)
    if failed_series:
        external_errors = "; ".join(
            f"{series_id}: {failed_series[series_id]}"
            for series_id in sorted(failed_series)
        )
        errors.append(f"external indicator acquisition: {external_errors}")
    if errors:
        merged["error"] = "; ".join(errors)[:2000]
    else:
        merged.pop("error", None)

    if combined_failed:
        merged["fallback_reason"] = "some_requested_series_failed"
    else:
        merged.pop("fallback_reason", None)

    # Manual monthly sources are an explicit acquisition mode, not a failed
    # automated transport. Keep their state visible for operators without
    # putting them in failed_series/unavailable or changing the release gate.
    if manual_series:
        merged["manual_series"] = dict(sorted(manual_series.items()))
    else:
        merged.pop("manual_series", None)

    availability = dict(merged.get("availability") or {})
    availability["state"] = (
        "STALE"
        if status in {"reused_same_content", "reused_after_provider_failure", "environmentally_blocked"}
        else "UNKNOWN"
    )
    availability.setdefault("calendar_status", "UNCONFIGURED")
    availability.setdefault("available_at", None)
    availability.setdefault("decision_usable", False)
    availability.setdefault(
        "reason", "publication_calendar_or_available_at_not_evidenced"
    )
    availability["retrieved_at"] = merged["retrieved_at"]
    merged["availability"] = availability
    return merged


def prefer_openbb() -> bool:
    """Whether registry routing should try OpenBB providers before direct FRED.

    Env ``HARVESTER_PREFER_OPENBB``:
      auto (default) — True when the ``openbb`` package imports
      1/true/on      — force prefer
      0/false/off    — force direct-provider order from YAML
    """
    raw = os.environ.get("HARVESTER_PREFER_OPENBB", "auto").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    return openbb_available()


def order_provider_priority(priority: list[str] | tuple[str, ...]) -> list[str]:
    """Put openbb_* providers first when prefer_openbb() is active."""
    items = list(priority)
    if not prefer_openbb():
        return items
    openbb_first = [p for p in items if str(p).startswith("openbb")]
    rest = [p for p in items if not str(p).startswith("openbb")]
    return openbb_first + rest


__all__ = [
    "_external_indicator_timeout_seconds",
    "_failed_attempt_failure_classes",
    "_is_external_managed_series",
    "_merge_external_provider_outcome",
    "_provider_outcome",
    "order_provider_priority",
    "prefer_openbb",
]
