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

celery_app.conf.beat_schedule = {
    # Generate daily analytics snapshots for all active bots at 00:05 UTC every day
    "generate-daily-bot-snapshots": {
        "task": "tasks.generate_all_bot_snapshots",
        "schedule": 86400.0,  # Every 24 hours (in seconds)
        # Cron alternative: crontab(hour=0, minute=5)
    },
}

# Auto-discover tasks from submodules inside app
celery_app.autodiscover_tasks(["app"])

# Explicitly import modules containing tasks to ensure registration
import app.tasks.ingestion  # noqa: F401
import app.tasks.analytics  # noqa: F401
