import logging
from pathlib import Path
from datetime import datetime

def setup_logger(name: str = "tm470", log_level: int = logging.INFO) -> logging.Logger:
    """
    Sets up a logger that writes to /logs/pipeline_<timestamp>.log and also prints to console.

    Args:
        name (str): Name of the logger instance. Defaults to "tm470".
        log_level (int): Logging level (e.g. logging.INFO, logging.DEBUG). Defaults to logging.INFO.

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
