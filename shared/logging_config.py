"""
Central Logging Configuration for HLD Generator.

Provides a standardized setup for logging across all modules,
ensuring consistent formatting, file output, and console output.
Includes automatic log file cleanup to prevent disk space issues.
"""

import logging
import sys
import os
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime

# Define log directory
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Default log format
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Maximum number of daily log files to keep (30 days worth)
MAX_LOG_FILES = 30


def cleanup_old_logs(log_dir: Path, max_files: int = MAX_LOG_FILES):
    """
    Remove old log files, keeping only the most recent ones.

    This prevents log files from accumulating indefinitely and consuming disk space.

    Args:
        log_dir: Directory containing log files
        max_files: Maximum number of log files to keep (default: 30)
    """
    try:
        # Get all .log files in the directory
        log_files = [f for f in log_dir.glob("*.log") if f.is_file()]

        # Sort by modification time (newest first)
        log_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

        # Delete files beyond the maximum
        if len(log_files) > max_files:
            deleted_count = 0
            for old_file in log_files[max_files:]:
                try:
                    old_file.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"Warning: Failed to delete old log file {old_file}: {e}", file=sys.stderr)

            if deleted_count > 0:
                print(f"Cleaned up {deleted_count} old log files from {log_dir}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error cleaning up log files in {log_dir}: {e}", file=sys.stderr)


def setup_logger(name: str = "hld_generator", log_level: int = logging.INFO, log_to_file: bool = True) -> logging.Logger:
    """
    Setup and configure a logger with console and optional file handlers.

    Args:
        name: Logger name (default: "hld_generator")
        log_level: Logging level (default: INFO)
        log_to_file: Whether to write logs to a file (default: True)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Avoid duplicate handlers if logger is already configured
    if logger.handlers:
        return logger

    # Console Handler with UTF-8 encoding to handle emoji characters on Windows
    console_handler = logging.StreamHandler(sys.stdout)
    # Set stream encoding to UTF-8 if possible (for Windows compatibility with emojis)
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass  # Fallback if reconfigure not available or fails
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    logger.addHandler(console_handler)

    # File Handler
    if log_to_file:
        # Clean up old log files before creating new handler
        cleanup_old_logs(LOG_DIR, MAX_LOG_FILES)

        timestamp = datetime.now().strftime("%Y%m%d")
        log_file = LOG_DIR / f"hld_generator_{timestamp}.log"
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(file_handler)

    return logger

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with the given name.
    Ensures the parent logger is configured if not already.
    """
    # Ensure root logger is configured if not already
    root_logger = logging.getLogger("hld_generator")
    if not root_logger.handlers:
        setup_logger("hld_generator")
        
    return logging.getLogger(f"hld_generator.{name}")
