"""E.4: Operational Health Report for data backend.

Generates a machine- and human-readable health report showing:
  - current backend
  - current release_id
  - series coverage
  - missing series
  - retired series
  - fallback status
  - cache status
  - network calls = 0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class HealthReport:
    current_backend: str
    current_release_id: str | None = None
    series_coverage: dict[str, Any] = field(default_factory=dict)
    missing_series: list[str] = field(default_factory=list)
    retired_series: list[str] = field(default_factory=list)
    fallback_status: str = "none"
    cache_status: str = "unknown"
    network_calls: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    generated_at: str = ""
    backend_details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.generated_at:
            self.generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_health_report(
    data_hub_or_lite: Any,
    *,
    backend: str = "",
    release_id: str | None = None,
    fallback_used: bool = False,
    network_calls: int = 0,
    backend_details: dict[str, Any] | None = None,
) -> HealthReport:
    """Build a health report from the current data backend."""

    # Determine series coverage
    series_coverage: dict[str, Any] = {}
    missing_series: list[str] = []
    retired_series: list[str] = []

    # Try to extract coverage from DataHubLite
    if hasattr(data_hub_or_lite, "panel") and data_hub_or_lite.panel is not None:
        panel = data_hub_or_lite.panel
        try:
            available = sorted(panel["source_series_id"].unique().tolist())
            date_col = panel["date"] if "date" in panel.columns else None
            series_coverage = {
                "available_count": len(available),
                "available_series": available,
                "total_rows": len(panel),
            }
            if date_col is not None:
                dates = pd_to_datetime_safe(date_col)
                if not dates.empty:
                    series_coverage["date_min"] = dates.min().strftime("%Y-%m-%d")
                    series_coverage["date_max"] = dates.max().strftime("%Y-%m-%d")
        except Exception:
            series_coverage = {"error": "could not extract panel coverage"}

    source_registry = _extract_source_registry(data_hub_or_lite)
    if source_registry:
        available_series = set(series_coverage.get("available_series", []))
        for s in _registry_series(source_registry, "required_series"):
            canonical_id = str(s.get("canonical_id") or s.get("id") or "")
            if not canonical_id or canonical_id in available_series:
                continue
            proxy_id = str(s.get("synthetic_proxy_id") or "")
            allow_proxy = bool(s.get("allow_synthetic_proxy", False))
            if allow_proxy and proxy_id and proxy_id not in available_series:
                missing_series.append(f"{canonical_id} (no proxy)")
            elif not allow_proxy:
                missing_series.append(canonical_id)
        retired_series.extend(
            str(s.get("canonical_id") or s.get("id"))
            for s in _registry_series(source_registry, "retired_series")
            if s.get("canonical_id") or s.get("id")
        )

    # Fallback status
    fallback_status = "active" if fallback_used else "none"

    # Cache status
    cache_status = "release_snapshot" if backend == "harvester" else "live_acquisition"

    warnings: list[str] = []
    if fallback_used:
        warnings.append(
            "Harvester backend failed; fallback to legacy DataHub. "
            "This path performs live acquisition and is deprecated."
        )
    if missing_series:
        warnings.append(f"Missing required series: {missing_series}")
    if network_calls > 0 and backend == "harvester":
        warnings.append(f"Network calls detected ({network_calls}) in Harvester-only mode")

    return HealthReport(
        current_backend=backend or "unknown",
        current_release_id=release_id,
        series_coverage=series_coverage,
        missing_series=missing_series,
        retired_series=retired_series,
        fallback_status=fallback_status,
        cache_status=cache_status,
        network_calls=network_calls,
        warnings=warnings,
        backend_details=backend_details or {},
    )


def health_report_markdown(report: HealthReport) -> str:
    """Render health report as Markdown."""
    lines: list[str] = []
    lines.append("# Data Backend Health Report")
    lines.append("")
    lines.append(f"**Generated**: {report.generated_at}")
    lines.append(f"**Backend**: `{report.current_backend}`")
    lines.append(f"**Release**: `{report.current_release_id or 'N/A'}`")
    lines.append(f"**Network calls**: {report.network_calls}")
    lines.append(f"**Cache status**: {report.cache_status}")
    lines.append(f"**Fallback status**: {report.fallback_status}")
    lines.append("")

    if report.warnings:
        lines.append("## Warnings")
        for w in report.warnings:
            lines.append(f"- ⚠ {w}")
        lines.append("")

    if report.errors:
        lines.append("## Errors")
        for e in report.errors:
            lines.append(f"- ❌ {e}")
        lines.append("")

    coverage = report.series_coverage
    if coverage:
        lines.append("## Series Coverage")
        lines.append(f"- Available: {coverage.get('available_count', 0)} series")
        lines.append(f"- Total rows: {coverage.get('total_rows', 0)}")
        if coverage.get("date_min"):
            lines.append(f"- Date range: {coverage['date_min']} → {coverage['date_max']}")

    if report.missing_series:
        lines.append("")
        lines.append("## Missing Series")
        for s in report.missing_series:
            lines.append(f"- {s}")

    if report.retired_series:
        lines.append("")
        lines.append("## Retired Series")
        for s in report.retired_series:
            lines.append(f"- {s} (historical replay only)")

    lines.append("")
    lines.append("## Compliance")
    lines.append(f"- Network calls = 0: {'✓' if report.network_calls == 0 else '✗'}")
    lines.append(f"- Release identified: {'✓' if report.current_release_id else '✗'}")
    lines.append(f"- Fallback inactive: {'✓' if report.fallback_status == 'none' else '⚠'}")

    return "\n".join(lines)


def write_health_report(
    data_hub_or_lite: Any,
    *,
    output_dir: str | Path = "",
    backend: str = "",
    release_id: str | None = None,
    fallback_used: bool = False,
    network_calls: int = 0,
    backend_details: dict[str, Any] | None = None,
) -> Path:
    """Build and write health report to Output/reports/data_backend_health.md."""
    if not output_dir:
        output_dir = Path("Output/reports")
    odir = Path(output_dir)
    odir.mkdir(parents=True, exist_ok=True)

    report = build_health_report(
        data_hub_or_lite,
        backend=backend,
        release_id=release_id,
        fallback_used=fallback_used,
        network_calls=network_calls,
        backend_details=backend_details,
    )

    md_path = odir / "data_backend_health.md"
    md_path.write_text(health_report_markdown(report), encoding="utf-8")

    import json as _json
    json_path = odir / "data_backend_health.json"
    json_path.write_text(_json.dumps({
        "current_backend": report.current_backend,
        "current_release_id": report.current_release_id,
        "series_coverage": report.series_coverage,
        "missing_series": report.missing_series,
        "retired_series": report.retired_series,
        "fallback_status": report.fallback_status,
        "cache_status": report.cache_status,
        "network_calls": report.network_calls,
        "warnings": report.warnings,
        "errors": report.errors,
        "generated_at": report.generated_at,
    }, indent=2, default=str) + "\n", encoding="utf-8")

    return md_path


def pd_to_datetime_safe(series: Any) -> Any:
    import pandas as pd
    try:
        return pd.to_datetime(series)
    except Exception:
        return pd.Series(dtype="datetime64[ns]")


def _extract_source_registry(data_hub_or_lite: Any) -> dict[str, Any]:
    registry = getattr(data_hub_or_lite, "source_registry", None)
    if isinstance(registry, dict):
        return registry
    bundle = getattr(data_hub_or_lite, "bundle", None)
    registry = getattr(bundle, "source_registry", None)
    return registry if isinstance(registry, dict) else {}


def _registry_series(source_registry: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = source_registry.get(key, [])
    if isinstance(values, dict):
        values = values.values()
    if not isinstance(values, list):
        values = list(values) if values else []
    return [item for item in values if isinstance(item, dict)]


__all__ = [
    "HealthReport",
    "build_health_report",
    "health_report_markdown",
    "write_health_report",
]
