"""
Deprecated shim: transformer logic moved to mht.transform.pipeline.
Kept for backward compatibility with existing imports.
"""
from __future__ import annotations

from mht.transform.pipeline import run_transformer  # noqa: F401

__all__ = ["run_transformer"]
