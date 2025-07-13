"""
config.py

Defines global configuration constants used across the TM470 XML parsing pipeline,
including the centralised logging level.

All modules should import `LOG_LEVEL` from this file to ensure consistent behaviour.
"""

import logging

# Set global logging level for the entire project
# Options: logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR
LOG_LEVEL = logging.DEBUG
