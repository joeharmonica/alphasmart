"""
Centralised logger for AlphaSMART.
Uses loguru with file rotation and structured output.
"""
import sys
from pathlib import Path
from loguru import logger


def setup_logger(level: str = "INFO", log_file: str = "logs/alphasmart.log") -> None:
    """Configure logger with console and rotating file sinks."""
    logger.remove()

    # Console sink — coloured, human-readable
    logger.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # File sink — structured, rotated
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_file,
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{line} - {message}",
        rotation="10 MB",
        retention="30 days",
        compression="zip",
        enqueue=True,  # thread-safe
    )


# Auto-configure with defaults on import
setup_logger()

__all__ = ["logger", "setup_logger"]
