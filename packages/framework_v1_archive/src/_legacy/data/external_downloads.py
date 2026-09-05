"""
DEPRECATED PHASE A FAIL WRAPPER.

External public-indicator acquisition has moved out of Structural Deformation.
Use Structural Risk Harvester to acquire CISS, SRISK, CoVaR, and related
external indicators, then consume admitted Harvester releases through
src/data_access/.

This module intentionally performs no external HTTP, reads no provider API
keys, and manages no raw provider cache.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


_MESSAGE = (
    "src.data.external_downloads is deprecated in Structural Deformation. "
    "External indicator acquisition belongs in Structural Risk Harvester. "
    "Run the Harvester external-indicator acquisition command and consume the "
    "published admitted evidence release through src.data_access."
)


class ManualDownloadRequired(RuntimeError):
    """Compatibility error name retained for old callers."""


@dataclass(frozen=True)
class ExternalIndicator:
    name: str
    fred_compatible_id: str
    description: str
    publisher_url: str
    instructions: str


CISS = ExternalIndicator(
    name="CISS",
    fred_compatible_id="CISS",
    description="ECB Composite Indicator of Systemic Stress.",
    publisher_url="moved-to-harvester",
    instructions=_MESSAGE,
)
SRISK = ExternalIndicator(
    name="SRISK",
    fred_compatible_id="SRISK",
    description="NYU V-Lab aggregate SRISK.",
    publisher_url="moved-to-harvester",
    instructions=_MESSAGE,
)
COVAR = ExternalIndicator(
    name="COVAR",
    fred_compatible_id="COVAR",
    description="NY Fed delta-CoVaR systemic risk measure.",
    publisher_url="moved-to-harvester",
    instructions=_MESSAGE,
)
KNOWN_INDICATORS: tuple[ExternalIndicator, ...] = (CISS, SRISK, COVAR)
DEFAULT_CACHE_DIR = Path("moved-to-harvester")


def _deprecated(*_args: Any, **_kwargs: Any) -> None:
    raise RuntimeError(_MESSAGE)


def fetch_external_indicator(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


def fetch_all_external(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


def merge_external_into_frame(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


def write_template_csv(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


def _parse_ciss_csv(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


def _parse_srisk_csv(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


def _parse_covar_csv(*_args: Any, **_kwargs: Any) -> None:
    _deprecated()


__all__ = [
    "CISS",
    "SRISK",
    "COVAR",
    "DEFAULT_CACHE_DIR",
    "ExternalIndicator",
    "KNOWN_INDICATORS",
    "ManualDownloadRequired",
    "fetch_all_external",
    "fetch_external_indicator",
    "merge_external_into_frame",
    "write_template_csv",
]
