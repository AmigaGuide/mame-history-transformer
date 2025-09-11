"""
Filename: config.py
Version: 1.0.0
Last modified: 2025-09-10
Author: Jason (XtC) Skelly (Open University TM470, 2025)

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

__all__ = ["LOG_LEVEL"]

# Set global logging level for the entire project.
# Options include: logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR, logging.CRITICAL
LOG_LEVEL = logging.DEBUG
