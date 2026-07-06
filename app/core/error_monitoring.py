import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("app.error_monitoring")


class ErrorMonitoringService:
    """
    Centralized error monitoring foundation.
    Ready to integrate with Sentry, Datadog, or other APM systems in the future.
    """
    def __init__(self):
        # Placeholder for SDK client initialization (e.g. sentry_sdk.init())
        self.initialized = False
        self.provider = "logging"  # Future: "sentry" | "datadog" | etc.

    def capture_exception(
        self,
        exc: Exception,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Captures an exception, logs it, and prepares to forward it to external monitoring providers.
        """
        extra = {
            **(context or {}),
            "tags": tags or {}
        }
        logger.error(
            f"[CENTRAL ERROR] Exception captured: {str(exc)}",
            exc_info=exc,
            extra=extra
        )
        # Future integration hook:
        # if self.initialized and self.provider == "sentry":
        #     import sentry_sdk
        #     sentry_sdk.capture_exception(exc)

    def capture_message(
        self,
        message: str,
        level: str = "error",
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """
        Captures a text message or error log centrally.
        """
        log_level = getattr(logging, level.upper(), logging.ERROR)
        extra = {
            **(context or {}),
            "tags": tags or {}
        }
        logger.log(
            log_level,
            f"[CENTRAL LOG] Message: {message}",
            extra=extra
        )


# Global singleton instance
error_monitor = ErrorMonitoringService()
