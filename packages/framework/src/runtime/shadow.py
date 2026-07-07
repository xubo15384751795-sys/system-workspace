"""D.2: Runtime Assembly Shadow Mode.

When shadow_data_backend is configured, the primary backend still drives
runtime output, but a DataHubLite instance runs in parallel for comparison.
Results are diffed and a diagnostic report is generated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any



@dataclass
class ShadowReport:
    primary_backend: str
    shadow_backend: str
    series_count_primary: int = 0
    series_count_shadow: int = 0
    primary_errors: int = 0
    shadow_errors: int = 0
    common_series: set[str] = field(default_factory=set)
    primary_only: set[str] = field(default_factory=set)
    shadow_only: set[str] = field(default_factory=set)
    value_diffs: list[dict[str, Any]] = field(default_factory=list)
    metadata_diffs: list[dict[str, Any]] = field(default_factory=list)
    shadow_release_id: str = ""

    @property
    def is_consistent(self) -> bool:
        return len(self.primary_only) == 0 and len(self.value_diffs) == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_backend": self.primary_backend,
            "shadow_backend": self.shadow_backend,
            "series_count_primary": self.series_count_primary,
            "series_count_shadow": self.series_count_shadow,
            "primary_errors": self.primary_errors,
            "shadow_errors": self.shadow_errors,
            "common_series": sorted(self.common_series),
            "primary_only": sorted(self.primary_only),
            "shadow_only": sorted(self.shadow_only),
            "value_diffs": self.value_diffs[:20],
            "metadata_diffs": self.metadata_diffs[:20],
            "shadow_release_id": self.shadow_release_id,
            "is_consistent": self.is_consistent,
        }


class ShadowMode:
    """Dual-path shadow runner for assembly.py.

    Usage in assembly.py:
        shadow = ShadowMode(config)
        primary_result = primary_backend.fetch(...)
        shadow_result = shadow.fetch_shadow(...)
        report = shadow.compare(primary_result, shadow_result)
        shadow.write_report(report)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._lite = None
        self._adapter = None

    @property
    def enabled(self) -> bool:
        shadow = self.config.get("shadow_data_backend")
        return shadow == "harvester" or bool(
            (self.config.get("data_access") or {}).get("shadow_backend")
        )

    @property
    def primary_backend(self) -> str:
        return str(
            self.config.get("data_backend")
            or (self.config.get("data_access") or {}).get("backend")
            or "legacy"
        )

    @property
    def shadow_backend(self) -> str:
        return str(
            self.config.get("shadow_data_backend")
            or (self.config.get("data_access") or {}).get("shadow_backend")
            or "harvester"
        )

    def _ensure_lite(self) -> Any:
        if self._lite is not None:
            return self._lite
        from src.data_access.harvester_adapter import HarvesterAdapter
        from src.data.gateway.data_hub_lite import DataHubLite

        hcfg = self.config.get("harvester") or {}
        exports_root = hcfg.get("exports_root")
        if not exports_root:
            for key in ("harvester_root", "harvester_export_root"):
                val = (self.config.get("data_access") or {}).get(key)
                if val:
                    exports_root = val
                    break
        if not exports_root:
            exports_root = str(Path.cwd() / "Data" / "harvester" / "exports")

        self._adapter = HarvesterAdapter(
            exports_root=Path(exports_root),
            release=str(hcfg.get("release", "latest")),
            contract_root=str(hcfg.get("contract_root", "")),
            require_finalized=bool(hcfg.get("require_finalized", True)),
            validate_hashes=False,
            validate_schema=False,
        )
        self._lite = DataHubLite(adapter=self._adapter)
        return self._lite

    def fetch_shadow(
        self,
        series_requests: list[dict[str, Any]],
        start: str,
        end: str,
    ) -> Any:
        """Fetch series through DataHubLite (shadow path)."""
        lite = self._ensure_lite()
        return lite.fetch_series(series_requests, start=start, end=end)

    def fetch_shadow_presets(
        self,
        preset_names: list[str],
        start: str,
        end: str,
    ) -> Any:
        """Fetch structural presets through DataHubLite (shadow path)."""
        lite = self._ensure_lite()
        return lite.fetch_structural_presets(preset_names, start=start, end=end)

    def compare(
        self,
        primary_result: Any,
        shadow_result: Any,
    ) -> ShadowReport:
        """Compare primary and shadow FetchResults."""
        report = ShadowReport(
            primary_backend=self.primary_backend,
            shadow_backend=self.shadow_backend,
        )

        primary_items = list(getattr(primary_result, "items", []))
        shadow_items = list(getattr(shadow_result, "items", []))
        primary_errors = list(getattr(primary_result, "errors", []))
        shadow_errors = list(getattr(shadow_result, "errors", []))

        report.series_count_primary = len(primary_items)
        report.series_count_shadow = len(shadow_items)
        report.primary_errors = len(primary_errors)
        report.shadow_errors = len(shadow_errors)

        shadow_meta = dict(getattr(shadow_result, "metadata", {}))
        report.shadow_release_id = str(shadow_meta.get("release_id", ""))

        primary_keys = {
            getattr(item, "request_key", str(item)) for item in primary_items
        }
        shadow_keys = {
            getattr(item, "request_key", str(item)) for item in shadow_items
        }
        report.common_series = primary_keys & shadow_keys
        report.primary_only = primary_keys - shadow_keys
        report.shadow_only = shadow_keys - primary_keys

        return report

    def write_report(self, report: ShadowReport, output_dir: str | Path = "") -> Path:
        """Write shadow report to Output directory."""
        import json as _json
        odir = Path(output_dir) if output_dir else Path("Output/reports")
        odir.mkdir(parents=True, exist_ok=True)
        path = odir / "shadow_diff_report.json"
        path.write_text(_json.dumps(report.to_dict(), indent=2, default=str) + "\n", encoding="utf-8")
        return path

    def check_and_warn(self, report: ShadowReport) -> list[str]:
        """Check shadow report and return warnings."""
        warnings: list[str] = []
        if not report.is_consistent:
            warnings.append(
                f"Shadow divergence: primary={report.series_count_primary} "
                f"shadow={report.series_count_shadow} "
                f"primary_only={sorted(report.primary_only)} "
                f"shadow_only={sorted(report.shadow_only)}"
            )
        if report.shadow_errors > report.primary_errors:
            warnings.append(
                f"Shadow backend has more errors: "
                f"primary={report.primary_errors} shadow={report.shadow_errors}"
            )
        return warnings
