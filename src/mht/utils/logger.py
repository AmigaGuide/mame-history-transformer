"""
Filename: logger.py
Version: 1.0.0
Last modified: 2025-09-10
Author: Jason (XtC) Skelly (Open University TM470, 2025)

Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Purpose:
Provide a reusable logging facility for the whole pipeline. Creates timestamped log
files under ./logs and emits messages to both file and console. The effective level
is controlled centrally via config.LOG_LEVEL.

Key behaviours:
- `setup_logger(name="tm470", log_level=LOG_LEVEL)` initialises a named logger once,
  attaching a file handler and a console handler (avoids duplicate handlers on repeat calls).
- `debug_log(msg)` writes a DEBUG message prefixed with "[filename::function_name]".

Exports:
- setup_logger(name: str = "tm470", log_level: int = LOG_LEVEL) -> logging.Logger
- debug_log(message: str) -> None

Notes:
- Handler levels mirror the logger level at creation time; subsequent calls that pass
  a different log_level will *not* change existing handler levels (by design here).
- This module does not modify global/root logging configuration.

Licence:
This file forms part of a student project and is not intended for commercial use.
See repository LICENCE for details.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime
from pathlib import Path

#from config import LOG_LEVEL  # central log level configuration
#from .config import LOG_LEVEL
from mht.utils.config import LOG_LEVEL

__all__ = ["setup_logger", "debug_log"]


def setup_logger(name: str = "tm470", log_level: int = LOG_LEVEL) -> logging.Logger:
    """
    Initialise (or retrieve) a named logger that logs to a timestamped file and the console.

    The function is idempotent for a given `name`: it will not attach duplicate handlers
    if called multiple times.

    Args:
        name: Logger name (defaults to "tm470" for project-wide use).
        log_level: Logging level (e.g. logging.DEBUG / INFO / WARNING / ERROR / CRITICAL).

    Returns:
        A configured `logging.Logger` instance.
    """
    
    # Ensure logs directory exists; parents=True is harmless if it already does.
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Timestamped log filename for the current process run.
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"pipeline_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid attaching multiple identical handlers if called more than once.
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

        # File handler writes UTF-8 to ./logs/pipeline_<timestamp>.log
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler mirrors the same format/level
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

def debug_log(message: str) -> None:
    """
    Log a DEBUG message with a standard prefix "[filename::function_name] ".

    The prefix is derived from the caller's frame using `inspect`, to support your
    TM470 logging convention across modules (e.g. "[history_parser::parse_history_entries] ...").

    Args:
        message: The message to emit at DEBUG level.
    """

    # Identify the caller (one frame back from this helper).
    frame = inspect.currentframe().f_back  # type: ignore[assignment]
    function = frame.f_code.co_name if frame and frame.f_code else "<?>"
    module = inspect.getmodule(frame)
    # Module names appear as 'package.module'; keep final segment for brevity.
    filename = (module.__name__.split(".")[-1] if module and module.__name__ else "<??>")

    logging.getLogger("tm470").debug(f"[{filename}::{function}] {message}")