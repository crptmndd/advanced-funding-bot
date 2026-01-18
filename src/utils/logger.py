"""Logging configuration for the funding bot."""

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


_console = Console()
_logger: Optional[logging.Logger] = None


def setup_logger(
    name: str = "funding_bot",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Set up and configure the application logger.
    
    Args:
        name: Logger name
        level: Logging level
        log_file: Optional path to log file
        
    Returns:
        Configured logger instance
    """
    global _logger
    
    if _logger is not None:
        return _logger
    
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()
    
    # Rich console handler for pretty output
    console_handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    console_handler.setLevel(level)
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level)
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Get the application logger instance."""
    global _logger
    if _logger is None:
        return setup_logger()
    return _logger

