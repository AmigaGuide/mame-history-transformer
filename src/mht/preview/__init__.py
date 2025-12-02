"""
Web preview server for MAME-History-Transformer.

This package exposes `run_preview()` which starts a small Flask app to browse
the ExoticA-ready JSON (wiki + trivia) for the active release.
"""

from .server import run_preview

__all__ = ["run_preview"]
