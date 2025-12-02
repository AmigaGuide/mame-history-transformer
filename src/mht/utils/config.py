"""
Filename: config.py
Version: 1.0.1
Author: XtC

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Provide centralised configuration constants for the pipeline, chiefly the global
logging level, to ensure consistent diagnostic output across all modules.

Key behaviours:
- Exports LOG_LEVEL for use by logger.setup_logger and all project modules.
- Encourages importing from this module rather than hard-coding logging levels.

Exports:
- LOG_LEVEL: int (e.g. logging.DEBUG, logging.INFO)

Notes:
This file has no runtime side effects. Changing LOG_LEVEL affects log verbosity
project-wide on the next run.

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

import logging
import os


__all__ = ["LOG_LEVEL", "_IGNORED_TOP_N"]

# Set global logging level for the entire project.
# Options include: logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL
LOG_LEVEL = logging.DEBUG

_IGNORED_TOP_N = 25

# ---------------------------------------------------------------------------
# Web preview configuration
# ---------------------------------------------------------------------------

# Port used by `mht preview` (can be overridden via env var).
WEB_PREVIEW_PORT: int = int(os.getenv("MHT_WEB_PREVIEW_PORT", "8000"))

# Whether `mht preview` should auto-open the browser.
# Set MHT_WEB_PREVIEW_AUTO_OPEN=0 to disable.
_WEB_PREVIEW_AUTO_OPEN_ENV = os.getenv("MHT_WEB_PREVIEW_AUTO_OPEN", "1").lower()
WEB_PREVIEW_AUTO_OPEN: bool = _WEB_PREVIEW_AUTO_OPEN_ENV not in ("0", "false", "no")
