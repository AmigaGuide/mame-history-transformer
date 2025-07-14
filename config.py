"""
Filename: config.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Defines global configuration constants for the project. Primarily used to set the
global logging level (e.g. DEBUG or INFO) to ensure consistent diagnostic output
across all pipeline modules.

All modules should import from this file rather than hard-coding configuration values.

This file is part of a student project and is not intended for commercial use.
"""

import logging

# Set global logging level for the entire project
# Options: logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR
LOG_LEVEL = logging.DEBUG
