# Worker entrypoint for Celery CLI execution
from app.core.celery_app import celery_app

__all__ = ["celery_app"]
