"""System errors.

Every error inherits from SystemError so the event layer can route
by severity and stage.  Sub-types exist only where callers actually
catch them by type.
"""

from __future__ import annotations


class SystemError(Exception):
    """Base for all structured system errors."""
    severity: str = "error"
    stage: str = "unknown"


class ConfigurationError(SystemError):
    stage = "configuration"


class DataSourceError(SystemError):
    """Data acquisition or evidence problems."""
    stage = "evidence_acquisition"


class IntegrationError(SystemError):
    """ODE / dynamics integration failure."""
    stage = "ode_integration"


class OutputError(SystemError):
    stage = "output"
