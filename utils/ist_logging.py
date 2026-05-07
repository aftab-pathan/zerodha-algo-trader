"""
utils/ist_logging.py
Custom logging formatter that displays timestamps in IST (Asia/Kolkata) timezone.
"""

import logging
import time
from datetime import datetime
import pytz


class ISTFormatter(logging.Formatter):
    """Custom formatter that converts timestamps to IST."""
    
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.ist = pytz.timezone('Asia/Kolkata')
    
    def formatTime(self, record, datefmt=None):
        """Override formatTime to use IST timezone."""
        dt = datetime.fromtimestamp(record.created, tz=pytz.UTC)
        dt_ist = dt.astimezone(self.ist)
        
        if datefmt:
            return dt_ist.strftime(datefmt)
        else:
            # Default format with IST indicator
            return dt_ist.strftime('%Y-%m-%d %H:%M:%S IST')


def setup_ist_logging(level=logging.INFO, log_file=None):
    """
    Configure logging with IST timestamps.
    
    Args:
        level: Logging level (default: INFO)
        log_file: Optional log file path
    
    Returns:
        Configured logger
    """
    # Create formatter with IST timezone
    formatter = ISTFormatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S IST'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (if specified)
    if log_file:
        import os
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger
