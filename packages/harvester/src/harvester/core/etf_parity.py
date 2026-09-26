"""Non-authoritative Tiingo/Massive ETF parity lane.

Parity is evidence about semantic equivalence, not a provider health check.
The report is safe to generate in shadow mode and never certifies a fallback
without the configured overlap window and an explicit human-review marker.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

from harvester.core.source_drift import compare_normalized_frames, compare_source_signatures
from system_runtime.context import RuntimeContext


ETF_PARITY_SENTINELS = ("SPY", "QQQ", "HYG", "LQD", "TLT", "GLD", "UUP")
PARITY_SCHEMA_VERSION = "system.provider_parity_report.v1"


def _root() -> Path:
    return RuntimeContext.current_context().workspace


def parity_policy_path() -> Path:
    return _root() / "configs" / "provider_parity_policy.yaml"


def parity_policy_schema_path() -> Path:
    return _root() / "protocols" / "provider_parity_policy.schema.json"


def parity_report_path() -> Path:
    """Return the durable, human-reviewable parity report location."""
    try:
        policy = load_parity_policy()
        configured = str(policy.get("report_path") or "").strip()
        if configured:
            return _root() / configured
    except Exception:
        # A missing/invalid policy must never make a fallback permissive.
        pass
    return _root() / "Data" / "harvester" / "provider_parity" / "etf_provider_parity.json"


def load_latest_parity_report(path: Path | str | None = None) -> dict[str, Any] | None:
    """Read the reviewed parity report, if one exists, without network I/O."""
    target = Path(path) if path is not None else parity_report_path()
    try:
        payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def load_parity_policy(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else parity_policy_path()
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("provider parity policy must be a mapping")
    try:
        schema = json.loads(parity_policy_schema_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("provider parity policy schema is unavailable") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"provider parity policy failed schema validation: {detail}")
    return payload


def build_provider_parity_report(
    frames_by_provider: Mapping[str, Mapping[str, Any]],
    *,
    baseline_provider: str = "tiingo",
    candidate_provider: str = "massive",
    sentinels: tuple[str, ...] = ETF_PARITY_SENTINELS,
    minimum_overlap_rows: int = 20,
    minimum_coverage_ratio: float = 0.80,
    source_signatures: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    provider_diagnostics: Mapping[str, list[Mapping[str, Any]]] | None = None,
    captured_at: str | None = None,
    human_reviewed: bool = False,
) -> dict[str, Any]:
    """Compare normalized provider frames and return a deterministic decision.

    Frames are expected to be normalized by the owned provider adapters. A
    missing sentinel is represented as ``NO_DATA`` rather than silently
    omitted from the report.
    """
    baseline_frames = frames_by_provider.get(baseline_provider, {}) or {}
    candidate_frames = frames_by_provider.get(candidate_provider, {}) or {}
    rows: dict[str, dict[str, Any]] = {}
    all_passed = True
    for ticker in sentinels:
        left = baseline_frames.get(ticker)
        right = candidate_frames.get(ticker)
        if left is None or right is None:
            result = {"status": "NO_DATA", "overlap_rows": 0}
            all_passed = False
        else:
            value_columns = tuple(
                column
                for column in ("value", "close", "open", "high", "low")
                if column in left.columns and column in right.columns
            )
            result = compare_normalized_frames(left, right, value_columns=value_columns)
            overlap = int(result.get("overlap_rows", 0) or 0)
            denominator = max(1, min(len(left), len(right)))
            coverage = overlap / denominator
            result["coverage_ratio"] = round(coverage, 6)
            result["minimum_overlap_rows"] = int(minimum_overlap_rows)
            result["minimum_coverage_ratio"] = float(minimum_coverage_ratio)
            passed = (
                result.get("status") == "PARITY"
                and overlap >= minimum_overlap_rows
                and coverage >= minimum_coverage_ratio
            )
            result["passed"] = bool(passed)
            all_passed = all_passed and passed
        rows[ticker] = result

    signature_report: dict[str, Any] | None = None
    if source_signatures:
        baseline_sigs = source_signatures.get(baseline_provider, {}) or {}
        candidate_sigs = source_signatures.get(candidate_provider, {}) or {}
        overlapping = {
            ticker: baseline_sigs[ticker]
            for ticker in baseline_sigs
            if ticker in candidate_sigs
        }
        overlapping_right = {
            ticker: candidate_sigs[ticker]
            for ticker in overlapping
        }
        signature_report = compare_source_signatures(
            overlapping,
            overlapping_right,
            # Cross-provider parity expects different provider names; the
            # comparison is about adjustment and timestamp conventions.
            ignore_fields=("provider",),
        )
        if signature_report.get("status") != "PARITY":
            all_passed = False

    reviewed = bool(human_reviewed)
    certified = bool(all_passed and reviewed)
    if certified:
        status = "CERTIFIED"
    elif all_passed:
        status = "PARITY_PENDING_REVIEW"
    elif any(row.get("status") == "NO_DATA" for row in rows.values()):
        status = "INSUFFICIENT_DATA"
    elif any(row.get("status") == "SCHEMA_CHANGED" for row in rows.values()):
        status = "SCHEMA_CHANGED"
    else:
        status = "SOURCE_DRIFT"
    return {
        "schema_version": PARITY_SCHEMA_VERSION,
        "dataset_id": "cross_asset_daily_panel",
        "baseline_provider": baseline_provider,
        "candidate_provider": candidate_provider,
        "sentinels": list(sentinels),
        "status": status,
        "certified": certified,
        "promotion_allowed": certified,
        "human_reviewed": reviewed,
        "captured_at": captured_at or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "series": rows,
        "source_signatures": signature_report,
        # Keep transport/auth/rate-limit evidence separate from semantic
        # parity.  This is intentionally secret-free and lets operators tell
        # a recoverable provider incident from a source-drift finding.
        "provider_diagnostics": {
            str(provider): [dict(item) for item in items]
            for provider, items in (provider_diagnostics or {}).items()
        },
        "claim_ceiling": "observed_source_equivalence" if certified else "diagnostic_parity_only",
    }


def collect_live_provider_frames(
    *,
    data_root: Path | str,
    tickers: tuple[str, ...] = ETF_PARITY_SENTINELS,
    period: str = "60d",
    api_keys: Mapping[str, str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, dict[str, Any]]]]:
    """Fetch the two authenticated routes for an explicit shadow run.

    This function is intentionally not called from the scheduled release.
    A caller opts into the extra provider traffic and receives both frames and
    source signatures for the report writer.
    """
    frames, signatures, _diagnostics = _collect_live_provider_frames_with_diagnostics(
        data_root=data_root,
        tickers=tickers,
        period=period,
        api_keys=api_keys,
    )
    return frames, signatures


def _collect_live_provider_frames_with_diagnostics(
    *,
    data_root: Path | str,
    tickers: tuple[str, ...] = ETF_PARITY_SENTINELS,
    period: str = "60d",
    api_keys: Mapping[str, str] | None = None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    """Collect frames plus secret-free provider failure diagnostics."""
    from harvester.providers.etf_market_data import MassiveEodProvider, TiingoEodProvider

    keys = dict(api_keys or {})
    frames: dict[str, dict[str, Any]] = {"tiingo": {}, "massive": {}}
    signatures: dict[str, dict[str, dict[str, Any]]] = {"tiingo": {}, "massive": {}}
    diagnostics: dict[str, list[dict[str, Any]]] = {"tiingo": [], "massive": []}
    providers = {
        "tiingo": TiingoEodProvider(
            api_key=keys.get("tiingo"),
            period=period,
            data_root=data_root,
            cache=True,
        ),
        "massive": MassiveEodProvider(
            api_key=keys.get("massive"),
            period=period,
            data_root=data_root,
            cache=True,
        ),
    }
    # Panel acquisition keeps CRSP-adjusted Tiingo bars. Parity compares the
    # session OHLC both vendors actually publish; mixing adjClose with
    # Massive split-adjusted close is a convention mismatch, not drift.
    for provider in providers.values():
        provider.prefer_adjusted = False
    for provider_name, provider in providers.items():
        for result in provider.fetch_series(list(tickers)):
            if result is None or result.frame is None or result.frame.empty:
                if result is not None:
                    diagnostics[provider_name].append(
                        {
                            "series_id": str(result.series_id),
                            "error": str(result.fetch_error or ""),
                            "reason": str(result.fetch_fallback_reason or "unknown"),
                        }
                    )
                continue
            frames[provider_name][str(result.series_id)] = result.frame
            signature = result.source_params.get("source_signature")
            if isinstance(signature, dict):
                signatures[provider_name][str(result.series_id)] = dict(signature)
    for provider in providers.values():
        gateway = getattr(provider, "_gateway", None)
        if gateway is not None and hasattr(gateway, "close"):
            gateway.close()
    return frames, signatures, diagnostics


def build_live_provider_parity_report(
    *,
    data_root: Path | str,
    tickers: tuple[str, ...] = ETF_PARITY_SENTINELS,
    period: str = "60d",
    api_keys: Mapping[str, str] | None = None,
    human_reviewed: bool = False,
) -> dict[str, Any]:
    """Run an explicit Tiingo/Massive shadow comparison using policy values."""
    policy = load_parity_policy()
    frames, signatures, diagnostics = _collect_live_provider_frames_with_diagnostics(
        data_root=data_root,
        tickers=tickers,
        period=period,
        api_keys=api_keys,
    )
    return build_provider_parity_report(
        frames,
        baseline_provider=str(policy["preferred_provider"]),
        candidate_provider=str(policy["equivalent_fallback_provider"]),
        sentinels=tickers,
        minimum_overlap_rows=int(policy["minimum_overlap_rows"]),
        minimum_coverage_ratio=float(policy["minimum_coverage_ratio"]),
        source_signatures=signatures,
        provider_diagnostics=diagnostics,
        human_reviewed=human_reviewed,
    )


def route_policy_for_selection(
    selected_providers: Mapping[str, str] | None,
    *,
    parity_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify selected ETF routes without changing the data payload."""
    selected = {
        str(provider).lower()
        for provider in (selected_providers or {}).values()
        if str(provider).strip()
    }
    diagnostic_providers = {"yfinance"}
    authoritative_providers = {"tiingo", "massive"}
    fallback_requires_certification = True
    parity_required_providers = {"massive"}
    try:
        from harvester.core.source_spec import load_source_registry

        spec = load_source_registry().get("ETF_EOD_ADJUSTED")
        if spec is not None:
            diagnostic_providers = {route.source_id for route in spec.diagnostic_routes}
            authoritative_providers = {
                route.source_id for route in spec.authoritative_routes
            }
            parity_required_providers = {
                route.source_id
                for route in spec.routes
                if route.requires_parity_certification
            }
    except Exception:
        # Standalone package installs may not carry workspace configs. Keep a
        # conservative built-in policy rather than making the route permissive.
        pass
    try:
        parity_policy = load_parity_policy()
        fallback_requires_certification = bool(
            parity_policy.get("equivalent_fallback_requires_certification", True)
        )
    except Exception:
        # Conservative fallback when the workspace policy is unavailable.
        fallback_requires_certification = True
    effective_report = dict(parity_report) if isinstance(parity_report, Mapping) else load_latest_parity_report()
    certified = bool(effective_report and effective_report.get("certified"))
    diagnostic_selected = sorted(selected & diagnostic_providers)
    unknown_selected = sorted(selected - diagnostic_providers - authoritative_providers)
    if not selected:
        return {
            "route_class": "no_provider_selected",
            "selected_providers": [],
            "authoritative_providers": sorted(authoritative_providers),
            "diagnostic_providers": [],
            "unknown_providers": [],
            "diagnostic_only": True,
            "promotion_allowed": False,
            "decision_usable": False,
            "reason": "no_provider_route_was_selected",
            "parity_certified": certified,
        }
    if unknown_selected:
        return {
            "route_class": "unregistered_provider_route",
            "selected_providers": sorted(selected),
            "authoritative_providers": sorted(authoritative_providers),
            "diagnostic_providers": diagnostic_selected,
            "unknown_providers": unknown_selected,
            "diagnostic_only": True,
            "promotion_allowed": False,
            "decision_usable": False,
            "reason": "selected_provider_is_not_registered_in_source_registry",
            "parity_certified": certified,
        }
    if diagnostic_selected:
        return {
            "route_class": "diagnostic_fallback",
            "selected_providers": sorted(selected),
            "diagnostic_providers": diagnostic_selected,
            "authoritative_providers": sorted(authoritative_providers),
            "diagnostic_only": True,
            "promotion_allowed": False,
            "decision_usable": False,
            "reason": "yfinance_route_is_diagnostic_only_until_provider_parity_is_certified",
            "parity_certified": certified,
        }
    selected_authoritative = sorted(selected & authoritative_providers)
    if len(selected_authoritative) > 1:
        return {
            "route_class": "mixed_authoritative_provider_release",
            "selected_providers": sorted(selected),
            "diagnostic_providers": [],
            "authoritative_providers": selected_authoritative,
            "diagnostic_only": True,
            "promotion_allowed": False,
            "decision_usable": False,
            "reason": "release_mixes_equivalent_sources_without_release_level_cutover",
            "parity_certified": certified,
        }
    if (
        fallback_requires_certification
        and len(selected_authoritative) == 1
        and selected_authoritative[0] in parity_required_providers
        and not certified
    ):
        return {
            "route_class": "equivalent_fallback_pending_parity",
            "selected_providers": sorted(selected),
            "diagnostic_providers": [],
            "authoritative_providers": selected_authoritative,
            "diagnostic_only": True,
            "promotion_allowed": False,
            "decision_usable": False,
            "reason": "massive_fallback_requires_reviewed_tiingo_parity_report",
            "parity_certified": certified,
            "parity_report_path": str(parity_report_path()),
        }
    return {
        "route_class": "authoritative_provider_route",
        "selected_providers": sorted(selected),
        "diagnostic_providers": [],
        "authoritative_providers": sorted(authoritative_providers),
        "diagnostic_only": False,
        "promotion_allowed": True,
        "decision_usable": True,
        "reason": "selected_provider_is_registered_and_parity_eligible",
        "parity_certified": certified,
        "parity_report_path": str(parity_report_path()) if selected_authoritative == ["massive"] else None,
    }


__all__ = [
    "ETF_PARITY_SENTINELS",
    "PARITY_SCHEMA_VERSION",
    "build_provider_parity_report",
    "build_live_provider_parity_report",
    "collect_live_provider_frames",
    "load_parity_policy",
    "load_latest_parity_report",
    "parity_policy_path",
    "parity_policy_schema_path",
    "parity_report_path",
    "route_policy_for_selection",
]
