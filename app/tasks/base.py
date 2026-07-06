import logging
from typing import Any
from celery import Task

logger = logging.getLogger("app.tasks.base")


class BaseTask(Task):
    """
    A reusable base Celery task that provides robust error logging,
    automatic retry support, backoff configurations, and telemetry hooks.
    """
    # Automatic retry on any exception
    autoretry_for = (Exception,)
    # Exponential backoff: retry after 2^retry_number * retry_backoff (seconds)
    retry_backoff = True
    retry_backoff_max = 600  # Cap maximum delay at 10 minutes
    max_retries = 3

    def on_failure(self, exc: Exception, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        """
        Custom telemetry hook to log failures with detail.
        """
        from app.core.error_monitoring import error_monitor
        error_monitor.capture_exception(
            exc,
            context={
                "task_id": task_id,
                "task_name": self.name,
                "args": args,
                "kwargs": kwargs,
            },
            tags={"layer": "worker", "task_name": self.name}
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        """
        Custom telemetry hook to log successful runs.
        """
        logger.info(
            f"Task succeeded: {self.name}[{task_id}]",
            extra={
                "task_id": task_id,
                "task_name": self.name,
            }
        )
        super().on_success(retval, task_id, args, kwargs)
