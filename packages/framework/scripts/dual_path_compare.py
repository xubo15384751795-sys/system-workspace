"""Dual-path comparison: legacy DataHub vs DataHubLite from Harvester release.

D.1: Runs both backends on the same structural presets, compares:
  - series coverage
  - date ranges
  - value equality (within tolerance)
  - metadata differences
  - error differences

Output: diff report (dict/json/markdown).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class DualPathResult:
    """Result of a dual-path comparison run."""

    legacy_items: int = 0
    lite_items: int = 0
    legacy_errors: int = 0
    lite_errors: int = 0
    common_series: set[str] = field(default_factory=set)
    legacy_only_series: set[str] = field(default_factory=set)
    lite_only_series: set[str] = field(default_factory=set)
    value_comparisons: list[dict[str, Any]] = field(default_factory=list)
    metadata_diffs: list[dict[str, Any]] = field(default_factory=list)
    release_id: str = ""
    legacy_release_info: dict[str, Any] = field(default_factory=dict)
    lite_release_info: dict[str, Any] = field(default_factory=dict)

    @property
    def coverage_match(self) -> float:
        total = self.common_series | self.legacy_only_series | self.lite_only_series
        if not total:
            return 1.0
        return len(self.common_series) / len(total)

    @property
    def value_match_rate(self) -> float:
        if not self.value_comparisons:
            return 1.0
        matched = sum(1 for vc in self.value_comparisons if vc.get("within_tolerance", False))
        return matched / len(self.value_comparisons)


def _resolve_request_key(item: Any) -> str:
    """Best-effort request_key extraction from SeriesResult or dict."""
    if hasattr(item, "request_key"):
        return str(item.request_key)
    if isinstance(item, dict):
        return str(item.get("request_key", item.get("provider", "")))
    return str(item)


def _resolve_series_frame(item: Any) -> pd.DataFrame | None:
    """Extract a DataFrame from a SeriesResult or dict."""
    if hasattr(item, "frame"):
        f = item.frame
        if isinstance(f, pd.DataFrame):
            return f
    if isinstance(item, dict):
        f = item.get("frame")
        if isinstance(f, pd.DataFrame):
            return f
    return None


def compare_fetch_results(
    legacy_result: Any,
    lite_result: Any,
    *,
    value_tolerance: float = 1e-6,
) -> DualPathResult:
    """Compare two FetchResult objects and produce a DualPathResult."""
    result = DualPathResult()

    # Extract items and errors
    legacy_items = list(getattr(legacy_result, "items", []))
    lite_items = list(getattr(lite_result, "items", []))
    legacy_errors = list(getattr(legacy_result, "errors", []))
    lite_errors = list(getattr(lite_result, "errors", []))

    result.legacy_items = len(legacy_items)
    result.lite_items = len(lite_items)
    result.legacy_errors = len(legacy_errors)
    result.lite_errors = len(lite_errors)

    # Release info
    legacy_meta = dict(getattr(legacy_result, "metadata", {}))
    lite_meta = dict(getattr(lite_result, "metadata", {}))
    result.legacy_release_info = legacy_meta
    result.lite_release_info = lite_meta
    result.release_id = str(lite_meta.get("release_id", ""))

    # Series coverage
    legacy_keys = {_resolve_request_key(item) for item in legacy_items}
    lite_keys = {_resolve_request_key(item) for item in lite_items}
    result.common_series = legacy_keys & lite_keys
    result.legacy_only_series = legacy_keys - lite_keys
    result.lite_only_series = lite_keys - legacy_keys

    # Build lite index by request_key
    lite_index: dict[str, Any] = {_resolve_request_key(item): item for item in lite_items}

    # Value comparison per common series
    for item in legacy_items:
        rk = _resolve_request_key(item)
        if rk not in lite_index:
            continue
        legacy_frame = _resolve_series_frame(item)
        lite_item = lite_index[rk]
        lite_frame = _resolve_series_frame(lite_item)

        if legacy_frame is None or lite_frame is None:
            result.value_comparisons.append({
                "request_key": rk,
                "within_tolerance": False,
                "reason": "missing_frame",
            })
            continue

        comparison = _compare_frames(legacy_frame, lite_frame, value_tolerance)
        comparison["request_key"] = rk
        result.value_comparisons.append(comparison)

        # Metadata diff
        legacy_item_meta = dict(getattr(item, "metadata", {}))
        lite_item_meta = dict(getattr(lite_item, "metadata", {}))
        meta_diff = _diff_metadata(legacy_item_meta, lite_item_meta, rk)
        if meta_diff:
            result.metadata_diffs.append(meta_diff)

    return result


def _compare_frames(
    legacy: pd.DataFrame,
    lite: pd.DataFrame,
    tolerance: float = 1e-6,
) -> dict[str, Any]:
    """Compare two DataFrames for value equality within tolerance."""
    comp: dict[str, Any] = {
        "within_tolerance": True,
        "legacy_rows": len(legacy),
        "lite_rows": len(lite),
    }

    # Find common date column
    date_col = "date"
    if date_col not in legacy.columns or date_col not in lite.columns:
        # Try to find date column
        for col_name in legacy.columns:
            if "date" in str(col_name).lower():
                date_col = col_name
                break

    value_col = "value"
    if value_col not in legacy.columns or value_col not in lite.columns:
        # Try to find value column
        for col_name in legacy.columns:
            if str(col_name) not in (date_col, "series_id", "source_id", "source_series_id",
                                       "unit", "frequency", "vintage_date", "quality_flag"):
                value_col = col_name
                break

    # Date range comparison
    if date_col in legacy.columns and date_col in lite.columns:
        legacy_dates = pd.to_datetime(legacy[date_col])
        lite_dates = pd.to_datetime(lite[date_col])
        comp["legacy_date_min"] = legacy_dates.min().strftime("%Y-%m-%d") if not legacy_dates.empty else None
        comp["legacy_date_max"] = legacy_dates.max().strftime("%Y-%m-%d") if not legacy_dates.empty else None
        comp["lite_date_min"] = lite_dates.min().strftime("%Y-%m-%d") if not lite_dates.empty else None
        comp["lite_date_max"] = lite_dates.max().strftime("%Y-%m-%d") if not lite_dates.empty else None

    # Value comparison on overlapping dates
    if date_col in legacy.columns and date_col in lite.columns and value_col in legacy.columns and value_col in lite.columns:
        leg = legacy.set_index(date_col)[value_col].dropna()
        lit = lite.set_index(date_col)[value_col].dropna()
        common_dates = leg.index.intersection(lit.index)
        comp["common_dates"] = len(common_dates)
        if len(common_dates) > 0:
            diffs = (leg.loc[common_dates] - lit.loc[common_dates]).abs()
            comp["max_diff"] = float(diffs.max()) if not diffs.empty else 0.0
            comp["mean_diff"] = float(diffs.mean()) if not diffs.empty else 0.0
            comp["within_tolerance"] = (diffs <= tolerance).all()
            if not comp["within_tolerance"]:
                comp["exceeded_count"] = int((diffs > tolerance).sum())
                comp["exceeded_dates"] = [
                    str(d) for d in diffs[diffs > tolerance].index[:5]
                ]

    return comp


def _diff_metadata(
    legacy_meta: dict[str, Any],
    lite_meta: dict[str, Any],
    request_key: str,
) -> dict[str, Any] | None:
    """Compare per-series metadata, reporting meaningful differences."""
    diff: dict[str, Any] = {"request_key": request_key}
    changes: list[str] = []

    legacy_match = legacy_meta.get("match_strategy")
    lite_match = lite_meta.get("match_strategy")
    if legacy_match and lite_match and legacy_match != lite_match:
        changes.append(f"match_strategy: {legacy_match} → {lite_match}")

    for key in ("source_id", "source_series_id", "frequency", "unit"):
        lv = legacy_meta.get(key)
        dv = lite_meta.get(key)
        if lv and dv and str(lv) != str(dv):
            changes.append(f"{key}: {lv} → {dv}")

    # New fields present only in lite
    for key in ("risk_level", "quality_flag", "matched_source_id", "enrichment_source"):
        if key in lite_meta and key not in legacy_meta:
            changes.append(f"new_field: {key}={lite_meta[key]}")

    if not changes:
        return None

    diff["changes"] = changes
    return diff


def dual_path_report(result: DualPathResult, *, format: str = "markdown") -> str:
    """Render a DualPathResult as a Markdown or JSON report."""
    if format == "json":
        import json as _json
        return _json.dumps({
            "coverage_match": result.coverage_match,
            "value_match_rate": result.value_match_rate,
            "legacy_items": result.legacy_items,
            "lite_items": result.lite_items,
            "legacy_errors": result.legacy_errors,
            "lite_errors": result.lite_errors,
            "common_series": sorted(result.common_series),
            "legacy_only_series": sorted(result.legacy_only_series),
            "lite_only_series": sorted(result.lite_only_series),
            "release_id": result.release_id,
            "value_comparisons": result.value_comparisons[:20],
            "metadata_diffs": result.metadata_diffs[:20],
        }, indent=2, default=str)

    lines: list[str] = []
    lines.append("# Dual-Path Comparison Report")
    lines.append("")
    lines.append(f"**Release**: {result.release_id}")
    lines.append(f"**Coverage match**: {result.coverage_match:.1%}")
    lines.append(f"**Value match rate**: {result.value_match_rate:.1%}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Legacy | DataHubLite |")
    lines.append("|---|---|---|")
    lines.append(f"| Items | {result.legacy_items} | {result.lite_items} |")
    lines.append(f"| Errors | {result.legacy_errors} | {result.lite_errors} |")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"- Common: {len(result.common_series)} series")
    lines.append(f"- Legacy only: {result.legacy_only_series or 'none'}")
    lines.append(f"- Lite only: {result.lite_only_series or 'none'}")
    lines.append("")

    if result.value_comparisons:
        lines.append("## Value Comparisons")
        lines.append("")
        for vc in result.value_comparisons[:10]:
            rk = vc.get("request_key", "?")
            ok = "✓" if vc.get("within_tolerance") else "✗"
            lines.append(f"- {ok} **{rk}**: legacy={vc.get('legacy_rows')} rows, lite={vc.get('lite_rows')} rows, "
                         f"common_dates={vc.get('common_dates', 'N/A')}, "
                         f"max_diff={vc.get('max_diff', 'N/A')}")

    if result.metadata_diffs:
        lines.append("")
        lines.append("## Metadata Diffs")
        lines.append("")
        for md in result.metadata_diffs[:10]:
            lines.append(f"- **{md['request_key']}**: {', '.join(md['changes'])}")

    return "\n".join(lines)


def run_dual_path(
    preset_names: list[str] | None = None,
    start: str = "2026-04-01",
    end: str = "2026-05-01",
    *,
    config: dict[str, Any] | None = None,
    use_mock: bool = True,
    value_tolerance: float = 1e-6,
) -> DualPathResult:
    """Run both legacy DataHub and DataHubLite and compare results.

    This is the main entry point for D.1.
    """
    from src.core.runtime_context import RuntimePaths
    from src.data.gateway import create_data_hub
    from src.data.gateway.data_hub_lite import DataHubLite
    from src.data.paths import default_harvester_contract_root
    from src.data_access.harvester_adapter import HarvesterAdapter

    if preset_names is None:
        preset_names = [
            "dof_credit_depth_us",
            "dof_risk_transfer_breadth_us",
            "mismatch_curve_shape_us",
        ]

    # --- Legacy path ---
    cfg = dict(config or {})
    legacy_hub = create_data_hub(cfg, use_mock=use_mock)
    legacy_result = legacy_hub.fetch_structural_presets(preset_names, start=start, end=end)

    # --- Harvester path ---
    paths = (
        RuntimePaths.from_project_root(cfg["project_root"])
        if cfg.get("project_root")
        else RuntimePaths.discover()
    )
    adapter = HarvesterAdapter(
        exports_root=str(paths.harvester_root / "exports"),
        release="latest",
        contract_root=str(default_harvester_contract_root(cfg)),
        require_finalized=True,
        validate_hashes=False,
        validate_schema=False,
    )
    lite = DataHubLite(adapter=adapter)
    lite_result = lite.fetch_structural_presets(preset_names, start=start, end=end)

    # --- Compare ---
    return compare_fetch_results(legacy_result, lite_result, value_tolerance=value_tolerance)


__all__ = [
    "DualPathResult",
    "compare_fetch_results",
    "dual_path_report",
    "run_dual_path",
]
