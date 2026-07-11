"""
Analytics Celery Tasks
======================
Daily cron task to generate analytics snapshots for all active bots.
Scheduled via Celery Beat at 00:05 UTC every day.
"""
import logging
from app.core.celery_app import celery_app

logger = logging.getLogger("app.tasks.analytics")


@celery_app.task(name="tasks.generate_all_bot_snapshots", bind=True, max_retries=2)
def generate_all_bot_snapshots(self):
    """
    Celery Beat scheduled task — runs nightly at 00:05 UTC.
    Loops over all active bots and generates a daily snapshot for yesterday.
    """
    import asyncio
    from datetime import datetime, timedelta, timezone

    async def _run():
        from app.db.session import SessionLocal
        from app.services.snapshot_service import snapshot_service
        from sqlalchemy import select
        from app.models.bot import Bot

        snapshot_date = (datetime.now(timezone.utc) - timedelta(days=1)).date()

        async with SessionLocal() as db:
            result = await db.execute(select(Bot.id).where(Bot.is_active == True))
            bot_ids = [str(bid) for bid in result.scalars().all()]

        logger.info(f"Snapshot task: generating for {len(bot_ids)} bots on {snapshot_date}")

        for bot_id in bot_ids:
            try:
                await snapshot_service.generate_daily_snapshot(bot_id, snapshot_date)
            except Exception as e:
                logger.error(f"Snapshot task: failed for bot {bot_id}: {e}", exc_info=True)

        logger.info(f"Snapshot task: completed for {snapshot_date}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as exc:
        logger.error(f"Snapshot task failed: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=300)


@celery_app.task(name="tasks.generate_bot_snapshot_on_demand", bind=True)
def generate_bot_snapshot_on_demand(self, bot_id: str, date_str: str = None):
    """
    On-demand snapshot generation for a single bot.
    Called from admin API if manual refresh needed.
    """
    import asyncio
    from datetime import date

    async def _run():
        from app.services.snapshot_service import snapshot_service
        snapshot_date = date.fromisoformat(date_str) if date_str else None
        await snapshot_service.generate_daily_snapshot(bot_id, snapshot_date)
        logger.info(f"On-demand snapshot done: bot={bot_id} date={date_str}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
    except Exception as exc:
        logger.error(f"On-demand snapshot failed for bot {bot_id}: {exc}", exc_info=True)
