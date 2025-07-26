"""
Filename: logger.py

Author: Jason (XtC) Skelly (Open University TM470, 2025)

Part of the TM470 Project:
"Adapting MAME and Gaming-History XML Metadata for ExoticA’s Lost in Translation."

Description:
Sets up a reusable logging facility for the entire pipeline. Creates timestamped
log files in the /logs directory and outputs to both file and console. Logging
level is controlled via a global LOG_LEVEL setting defined in config.py.

This module ensures consistent and configurable runtime diagnostics across all scripts.

This file is part of a student project and is not intended for commercial use.
"""

import logging
import inspect
from pathlib import Path
from datetime import datetime
from config import LOG_LEVEL  # Import the global log level setting

def setup_logger(name: str = "tm470", log_level: int = LOG_LEVEL) -> logging.Logger:
    """
    Sets up a logger that writes to /logs/pipeline_<timestamp>.log and also prints to console.

    Args:
        name (str): Name of the logger instance. Defaults to "tm470".
        log_level (int): Logging level (e.g. logging.INFO, logging.DEBUG). Defaults to LOG_LEVEL from config.py.

    Returns:
        logging.Logger: Configured logger instance.
    """
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_file = log_dir / f"pipeline_{timestamp}.log"

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid duplicate handlers
    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

        # File handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

def debug_log(message: str):
    """
    Automatically prefixes debug messages with [filename::function_name].

    Args:
        message (str): Debug message to log.
    """
    frame = inspect.currentframe().f_back
    function = frame.f_code.co_name
    filename = inspect.getmodule(frame).__name__.split('.')[-1]
    logging.getLogger("tm470").debug(f"[{filename}::{function}] {message}")
