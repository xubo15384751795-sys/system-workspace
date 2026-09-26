"""Small, in-process protocol for governed measurement model plugins.

This is intentionally a protocol boundary, not a plugin marketplace or a
workflow framework.  Concrete models are loaded by the application boundary
and receive only the capabilities explicitly supplied by their host.
"""

from .protocol import (
    PROTOCOL_VERSION,
    DataAccess,
    DecisionEvidence,
    FileDataAccess,
    MeasurementModel,
    MeasurementRequest,
    ModelContext,
    ModelEvaluation,
    ModelHost,
    ModelManifest,
    ModelProtocolError,
    ModelResult,
    StateAdapter,
)

__all__ = [
    "PROTOCOL_VERSION",
    "DataAccess",
    "DecisionEvidence",
    "FileDataAccess",
    "MeasurementModel",
    "MeasurementRequest",
    "ModelContext",
    "ModelEvaluation",
    "ModelHost",
    "ModelManifest",
    "ModelProtocolError",
    "ModelResult",
    "StateAdapter",
]
