"""Dagster orchestration for registry-driven daily and refresh pipelines."""

__all__ = ["defs"]


def __getattr__(name: str):
    if name == "defs":
        from orchestration.definitions import defs as _defs

        return _defs
    raise AttributeError(name)
