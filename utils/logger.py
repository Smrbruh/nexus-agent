"""
utils/logger.py — Centralized, colored logging for NEXUS Agent
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False


def setup_logger(name: str = "nexus", level: str = "INFO", log_file: str = "logs/nexus.log") -> logging.Logger:
    """
    Create and configure a logger with both console (colored) and file handlers.
    """
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger  # Already configured

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # Console handler
    if HAS_COLORLOG:
        color_fmt = (
            "%(log_color)s%(asctime)s | %(levelname)-8s%(reset)s | "
            "%(cyan)s%(name)s%(reset)s | %(message)s"
        )
        console_handler = colorlog.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            colorlog.ColoredFormatter(
                color_fmt,
                datefmt=date_fmt,
                log_colors={
                    "DEBUG": "white",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
            )
        )
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))

    # Rotating file handler (10MB per file, keep 5 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


# Module-level default logger
log = setup_logger()
