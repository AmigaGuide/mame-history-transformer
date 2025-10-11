"""
Filename: logger.py
Author: XtC

Purpose:
Lightweight project-wide logging helper: one file + console, UTC timestamps.
"""

from __future__ import annotations

import inspect
import logging
import time
from datetime import datetime
from pathlib import Path

from .config import LOG_LEVEL


__all__ = ["setup_logger", "debug_log"]

# Single timestamped logfile per process run
_LOG_DIR = Path("logs")
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / f"pipeline_{datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}.log"


class _UtcFormatter(logging.Formatter):
    converter = time.gmtime  # UTC for %(asctime)s

def setup_logger(name: str = "mht", log_level: int = LOG_LEVEL) -> logging.Logger:
    """Initialise/retrieve a named logger with file + console handlers (idempotent)."""
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False

    if not logger.handlers:
        fmt = "%(asctime)sZ [%(levelname)s] %(message)s"
        datefmt = "%Y-%m-%dT%H:%M:%S"
        formatter = _UtcFormatter(fmt=fmt, datefmt=datefmt)

        fh = logging.FileHandler(_LOG_FILE, encoding="utf-8")
        fh.setLevel(log_level)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(log_level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger

def debug_log(message: str) -> None:
    """Emit a DEBUG line prefixed with [module::function]."""
    frame = inspect.currentframe().f_back  # type: ignore[assignment]
    func = frame.f_code.co_name if frame and frame.f_code else "<?>"
    mod = inspect.getmodule(frame)
    modname = (mod.__name__.split(".")[-1] if mod and mod.__name__ else "<??>")
    logging.getLogger("mht").debug(f"[{modname}::{func}] {message}")

def maybe_log_progress(
    log,
    count: int,
    *,
    step: int = 5000,
    prefix: str = "",
    fmt: str = "{prefix} Parsed {count:,} machines so far...",
) -> None:
    """
    Emit a progress info log every `step` items.

    Parameters
    ----------
    log
        Logger with .info(...)
    count
        Current item count (e.g., machines parsed)
    step
        Frequency to log at (default 5000)
    prefix
        String placed at the start of the message (e.g., "[mame_parser::parse_mame_xml]")
    fmt
        Format string with {prefix} and {count} placeholders. Defaults to the message used in mame_parser.

    Notes
    -----
    - Does nothing when count == 0.
    - Only logs when count % step == 0.
    """
    if count and (count % step) == 0:
        log.info(fmt.format(prefix=prefix, count=count))
