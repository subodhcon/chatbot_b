import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from app.core.config import settings

class StructuredFormatter(logging.Formatter):
    """
    Custom log formatter outputting clear key-value structures.
    Easily parseable for external log forwarders (Elasticsearch, Logstash, Datadog).
    """
    def format(self, record: logging.LogRecord) -> str:
        # Build standard log structure
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage()
        }
        
        # Append exceptions if they exist
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            
        return f"{log_data['timestamp']} [{log_data['level']}] {log_data['logger']}: {log_data['message']}" + (
            f"\n{log_data['exception']}" if "exception" in log_data else ""
        )

def setup_logging() -> None:
    """
    Setup logging configuration including console stream output and rotating files.
    """
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    
    # Create logs directory if it doesn't exist
    os.makedirs(settings.LOG_DIR, exist_ok=True)
    
    # Define paths
    app_log_path = os.path.join(settings.LOG_DIR, settings.LOG_FILE_NAME)
    err_log_path = os.path.join(settings.LOG_DIR, settings.ERROR_LOG_FILE_NAME)
    
    # Standard Formatter
    formatter = StructuredFormatter(datefmt="%Y-%m-%dT%H:%M:%S%z")
    
    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)
    
    # Application File Handler (All logs)
    app_file_handler = RotatingFileHandler(
        app_log_path,
        maxBytes=settings.LOG_ROTATION_MAX_BYTES,
        backupCount=settings.LOG_ROTATION_BACKUP_COUNT,
        encoding="utf-8"
    )
    app_file_handler.setFormatter(formatter)
    app_file_handler.setLevel(log_level)
    
    # Error File Handler (Only Warnings, Errors, and Criticals)
    err_file_handler = RotatingFileHandler(
        err_log_path,
        maxBytes=settings.LOG_ROTATION_MAX_BYTES,
        backupCount=settings.LOG_ROTATION_BACKUP_COUNT,
        encoding="utf-8"
    )
    err_file_handler.setFormatter(formatter)
    err_file_handler.setLevel(logging.WARNING)
    
    # Configure Root Logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid double logging
    root_logger.handlers = []
    
    # Add new handlers
    root_logger.addHandler(console_handler)
    root_logger.addHandler(app_file_handler)
    root_logger.addHandler(err_file_handler)
    
    # Suppress verbose dependency logs
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
