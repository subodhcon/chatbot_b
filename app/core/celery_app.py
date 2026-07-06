from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "chatbot_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_send_sent_event=True,  # Enables monitoring tools like Flower to track events
)

# Auto-discover tasks from submodules inside app
celery_app.autodiscover_tasks(["app"])

# Explicitly import modules containing tasks to ensure registration
import app.tasks.ingestion  # noqa: F401



