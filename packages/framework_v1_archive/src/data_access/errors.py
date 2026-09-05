from __future__ import annotations


class EvidenceBoundaryError(RuntimeError):
    """Raised when code tries to cross the admitted-evidence boundary."""


class MissingReleaseError(FileNotFoundError):
    """Raised when an admitted evidence release cannot be found."""


class InvalidEvidenceError(RuntimeError):
    """Raised when admitted evidence is missing required structure or integrity."""
