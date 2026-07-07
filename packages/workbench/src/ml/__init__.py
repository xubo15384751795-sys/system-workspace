"""Workbench ML layer.

Classical ML and GNN-based modules for the Workbench.
Heavy dependencies (torch, torch-geometric) are optional; every module
falls back to a numpy-only implementation when they are absent.
"""
from __future__ import annotations
