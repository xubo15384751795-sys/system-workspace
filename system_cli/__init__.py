"""Compatibility namespace for the retired ``system`` CLI package."""

__all__ = ["main"]


def __getattr__(name: str):
    if name == "main":
        from .app import main

        return main
    raise AttributeError(name)
