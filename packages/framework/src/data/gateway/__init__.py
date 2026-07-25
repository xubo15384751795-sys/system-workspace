"""Legacy shim — re-exports from src/_legacy/data/.

bridge.py and data_hub.py were moved to src/_legacy/data/ on 2026-06-29.
This __init__.py provides backward-compatible re-exports for transitional consumers.
retire_after: 2026-10-15 (SEAL extended 2026-07-03: keep read-only until DuckDB migration evidence window closes)
"""
import warnings

warnings.warn(
    "Importing from src.data.gateway is deprecated. "
    "Use src/data_access/ for Harvester-admitted evidence. "
    "This shim will be retired after 2026-10-15.",
    DeprecationWarning,
    stacklevel=2,
)

from src._legacy.data.bridge import DataHubBridge
from src._legacy.data.data_hub import DataHub, create_data_hub
from src.data.gateway.evidence_router import EvidenceRequest, EvidenceRoute, EvidenceRouter, ProviderCapability
from src.data.gateway.source_registry import SourceRegistry

__all__ = [
    "DataHub",
    "DataHubBridge",
    "EvidenceRequest",
    "EvidenceRoute",
    "EvidenceRouter",
    "ProviderCapability",
    "SourceRegistry",
    "create_data_hub",
]
