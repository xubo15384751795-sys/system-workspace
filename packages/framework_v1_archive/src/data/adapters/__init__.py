"""
LEGACY ACQUISITION SHIM.
This package re-exports legacy public-provider adapters for compatibility.
New Deformation code must use src/data_access/ and Harvester-admitted evidence.
retire_after: 2026-10-15
"""

from src._legacy.data.public_adapters import (
    AlphaVantageSeriesAdapter,
    CBOESeriesAdapter,
    CFTCPositionAdapter,
    ECBSeriesAdapter,
    FREDSeriesAdapter,
    FedH41SeriesAdapter,
    GenericCSVSeriesAdapter,
    IMFSeriesAdapter,
    MockEventAdapter,
    MockFilingAdapter,
    MockPositionAdapter,
    MockSeriesAdapter,
    NasdaqDataLinkSeriesAdapter,
    PolygonSeriesAdapter,
    SECFilingAdapter,
    SECSeriesAdapter,
    StooqSeriesAdapter,
    TiingoSeriesAdapter,
    TreasuryEventAdapter,
    TreasurySeriesAdapter,
)

__all__ = [
    "AlphaVantageSeriesAdapter",
    "CBOESeriesAdapter",
    "CFTCPositionAdapter",
    "ECBSeriesAdapter",
    "FREDSeriesAdapter",
    "FedH41SeriesAdapter",
    "GenericCSVSeriesAdapter",
    "IMFSeriesAdapter",
    "MockEventAdapter",
    "MockFilingAdapter",
    "MockPositionAdapter",
    "MockSeriesAdapter",
    "NasdaqDataLinkSeriesAdapter",
    "PolygonSeriesAdapter",
    "SECFilingAdapter",
    "SECSeriesAdapter",
    "StooqSeriesAdapter",
    "TiingoSeriesAdapter",
    "TreasuryEventAdapter",
    "TreasurySeriesAdapter",
]
"""
LEGACY ACQUISITION SHIM.
This package re-exports legacy public-provider adapters for compatibility.
New Deformation code must use src/data_access/ and Harvester-admitted evidence.
retire_after: 2026-10-15
"""
