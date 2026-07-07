from __future__ import annotations

from src.dynamics.state_evolution import DiffraxODEEngine


class ScipyODEEngine(DiffraxODEEngine):
    """
    Backward-compatible name for the adaptive state evolution engine.

    Existing callers can keep importing `ScipyODEEngine`; the implementation now
    prefers Diffrax/JAX when available and falls back to SciPy/RK4 otherwise.
    """
