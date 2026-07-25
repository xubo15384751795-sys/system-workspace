"""Legacy data module — retire_after: 2026-10-15."""
from src.data.contracts import (
    EventRecord,
    EventRequest,
    FetchResult,
    FilingRecord,
    FilingRequest,
    PositionRecord,
    PositionRequest,
    SeriesRequest,
    SeriesResult,
    StructuralFetchPlan,
    StructuralPreset,
    StructuralPresetResult,
    build_structural_fetch_plan,
    default_structural_presets,
)
# Legacy DataHub symbols (DataHub, SourceRegistry, create_data_hub) are no longer
# exported from the public data package. They remain available under:
#   from src.data.gateway import DataHub, SourceRegistry, create_data_hub
# with explicit ALLOW_LEGACY_DATAHUB=1 opt-in.

# Distributional measurement layer
from src.data.distribution import (
    ChannelDistributionState,
    CrossWindowStability,
    DistributionSummary,
    DensitySummary,
    RollingDispersion,
    WindowTransition,
    compute_cross_window_stability,
    compute_density,
    compute_rolling_dispersion,
    compute_transition,
)

# Cross-sectional layer
from src.data.cross_section import (
    CrossSectionAggregator,
    CrossSectionSlice,
    build_cross_section_slice,
)

# Data quality / tier / lineage layer
from src.data.quality import (
    DataSelector,
    DataTier,
    LineageRegistry,
    StructuralLineage,
    TieredSeriesSpec,
)

__all__ = [
    # Legacy gateway symbols (DataHub, SourceRegistry, create_data_hub) removed —
    # use explicit import from src.data.gateway with ALLOW_LEGACY_DATAHUB=1 opt-in.
    # contracts
    "EventRecord",
    "EventRequest",
    "FetchResult",
    "FilingRecord",
    "FilingRequest",
    "PositionRecord",
    "PositionRequest",
    "SeriesRequest",
    "SeriesResult",
    "StructuralFetchPlan",
    "StructuralPreset",
    "StructuralPresetResult",
    "build_structural_fetch_plan",
    "default_structural_presets",
    # distribution
    "ChannelDistributionState",
    "CrossWindowStability",
    "DistributionSummary",
    "DensitySummary",
    "RollingDispersion",
    "WindowTransition",
    "compute_cross_window_stability",
    "compute_density",
    "compute_rolling_dispersion",
    "compute_transition",
    # cross section
    "CrossSectionAggregator",
    "CrossSectionSlice",
    "build_cross_section_slice",
    # quality
    "DataSelector",
    "DataTier",
    "LineageRegistry",
    "StructuralLineage",
    "TieredSeriesSpec",
]
