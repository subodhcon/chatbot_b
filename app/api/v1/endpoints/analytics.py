import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from typing import Optional, Any
from app.db.session import get_async_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.bot import Bot
from app.models.bot_config import BotConfig
from app.core.responses import api_success_response, api_error_response
from app.services.analytics_aggregation import analytics_aggregation_service
from app.services.csat_calculation import csat_calculation_service
from app.services.deflection_rate import deflection_rate_service
from app.services.csv_export import csv_export_service
from app.repositories.export_job import export_job_repository
from app.models.export_job import ExportJobStatus
from app.utils.redis import get_redis
from app.utils.cache import get_cached_val, set_cached_val
from app.services.snapshot_service import snapshot_service

router = APIRouter()

@router.get("/summary", status_code=status.HTTP_200_OK)
async def get_analytics_summary(
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    redis: Any = Depends(get_redis),
):
    """
    Retrieve live aggregated statistics for the logged-in user's admin dashboard.
    """
    try:
        cache_key = f"cache:analytics_summary:{current_user.id}"
        cached = await get_cached_val(redis, cache_key)
        if cached is not None:
            return api_success_response(data=cached)

        # 1. Active Chatbots Count
        bot_query = select(func.count(Bot.id)).where(Bot.created_by == current_user.id).where(Bot.is_active == True)
        bot_res = await db.execute(bot_query)
        active_bots = bot_res.scalar() or 0

        # All user's bots (to filter conversations)
        user_bots_query = select(Bot.id).where(Bot.created_by == current_user.id)
        user_bots_res = await db.execute(user_bots_query)
        bot_ids = user_bots_res.scalars().all()

        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("analytics", settings.MONGODB_URL)
        mongo_db = mongo_client["chatbot"] if mongo_client else None

        # 2. Conversations (24h)
        conv_24h_count = 0
        if bot_ids and mongo_db:
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            conv_24h_count = await mongo_db["conversations"].count_documents({
                "bot_id": {"$in": [str(bid) for bid in bot_ids]},
                "created_at": {"$gte": since_24h}
            })

        # 3. Knowledge Docs Count
        knowledge_docs = 0
        if mongo_db:
            knowledge_docs = await mongo_db["documents"].count_documents({
                "created_by": str(current_user.id)
            })

        # 4. Success Rate & Avg. Chat Time
        success_rate = 100.0
        total_sessions = 0
        avg_chat_time_seconds = 0

        if bot_ids and mongo_db:
            # Total sessions
            total_sessions = await mongo_db["conversations"].count_documents({
                "bot_id": {"$in": [str(bid) for bid in bot_ids]}
            })

            # Calculate Success Rate
            if total_sessions > 0:
                bot_config_query = (
                    select(BotConfig.bot_id, BotConfig.fallback_message)
                    .join(Bot, BotConfig.bot_id == Bot.id)
                    .where(Bot.created_by == current_user.id)
                )
                bot_config_res = await db.execute(bot_config_query)
                bot_config_map = {str(r.bot_id): r.fallback_message for r in bot_config_res.all()}

                conv_cursor = mongo_db["conversations"].find(
                    {"bot_id": {"$in": [str(bid) for bid in bot_ids]}},
                    {"_id": 1, "bot_id": 1}
                )
                conv_bot_map = {}
                async for c_doc in conv_cursor:
                    conv_bot_map[c_doc["_id"]] = c_doc["bot_id"]

                fallback_hits = 0
                total_bot_responses = 0

                if conv_bot_map:
                    messages_coll = mongo_db["messages"]
                    cursor = messages_coll.find({
                        "conversation_id": {"$in": list(conv_bot_map.keys())},
                        "sender": "bot"
                    })
                    async for doc in cursor:
                        total_bot_responses += 1
                        conv_id = doc.get("conversation_id")
                        content = doc.get("content", "")
                        bot_id_str = conv_bot_map.get(conv_id)
                        fallback = bot_config_map.get(bot_id_str)
                        if fallback and content == fallback:
                            fallback_hits += 1

                if total_bot_responses > 0:
                    success_rate = round(((total_bot_responses - fallback_hits) / total_bot_responses) * 100, 1)

            # Calculate Avg. Session Duration
            conv_ids = list(conv_bot_map.keys()) if 'conv_bot_map' in locals() else []
            if conv_ids:
                from app.core.config import settings
                from app.core.mongo import mongo_registry
                mongo_client = mongo_registry.get_client("analytics", settings.MONGODB_URL)
                if mongo_client:
                    messages_coll = mongo_client["chatbot"]["messages"]
                    pipeline = [
                        {"$match": {"conversation_id": {"$in": conv_ids}}},
                        {"$group": {
                            "_id": "$conversation_id",
                            "min_time": {"$min": "$created_at"},
                            "max_time": {"$max": "$created_at"}
                        }}
                    ]
                    cursor = messages_coll.aggregate(pipeline)
                    async for doc in cursor:
                        durations.append((doc["_id"], doc["min_time"], doc["max_time"]))

            if durations:
                total_duration_secs = 0
                for _, min_time, max_time in durations:
                    if min_time and max_time:
                        total_duration_secs += (max_time - min_time).total_seconds()
                avg_chat_time_seconds = int(total_duration_secs / len(durations))

        # Format average chat time e.g., "3m 42s" or "12s"
        if avg_chat_time_seconds >= 60:
            minutes = avg_chat_time_seconds // 60
            seconds = avg_chat_time_seconds % 60
            avg_chat_time = f"{minutes}m {seconds}s"
        else:
            avg_chat_time = f"{avg_chat_time_seconds}s"

        summary_data = {
            "active_chatbots": active_bots,
            "conversations_24h": conv_24h_count,
            "knowledge_docs": knowledge_docs,
            "success_rate": f"{success_rate}%",
            "total_sessions": total_sessions,
            "avg_chat_time": avg_chat_time,
        }

        # Cache summary for 5 minutes
        await set_cached_val(redis, cache_key, summary_data, expire_seconds=300)

        return api_success_response(data=summary_data)


    except Exception as e:
        return api_error_response(
            message="An error occurred while computing analytics summary.",
            code="ANALYTICS_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/bots/{bot_id}", status_code=status.HTTP_200_OK)
async def get_bot_dashboard_analytics(
    bot_id: uuid.UUID,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve live aggregated analytics dashboard data for a specific chatbot.
    Must belong to the logged-in admin user (JWT protected).
    """
    try:
        # 1. Verify bot exists and belongs to the current user
        bot_query = select(Bot).where(Bot.id == bot_id, Bot.created_by == current_user.id)
        bot_res = await db.execute(bot_query)
        bot = bot_res.scalar_one_or_none()
        
        if not bot:
            return api_error_response(
                message="Bot not found or access denied.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 2. Fetch basic aggregations (conversations count, messages count)
        summary = await analytics_aggregation_service.get_bot_summary_metrics(
            db, bot_id=bot_id, start_date=start_date, end_date=end_date
        )

        # 3. Calculate CSAT percentage
        csat = await csat_calculation_service.calculate_csat(
            db, bot_id=bot_id, start_date=start_date, end_date=end_date
        )

        # 4. Calculate deflection rate
        deflection_rate = await deflection_rate_service.calculate_deflection_rate(
            db, bot_id=bot_id, start_date=start_date, end_date=end_date
        )

        # 5. Fetch daily conversation volume (default to past 30 days)
        volume = await analytics_aggregation_service.get_conversation_volume(
            db, bot_id=bot_id, days_limit=30
        )

        dashboard_data = {
            "total_conversations": summary["total_conversations"],
            "total_messages": summary["total_messages"],
            "csat": csat,
            "deflection_rate": deflection_rate,
            "conversation_volume": volume,
        }

        return api_success_response(data=dashboard_data)

    except Exception as e:
        return api_error_response(
            message="An error occurred while compiling bot dashboard analytics.",
            code="BOT_ANALYTICS_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ExportRequest(BaseModel):
    start_date: datetime
    end_date: datetime


@router.post("/bots/{bot_id}/export", status_code=status.HTTP_201_CREATED)
async def create_bot_data_export(
    bot_id: uuid.UUID,
    payload: ExportRequest,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Trigger a new conversation and ratings data CSV export job for a specific bot.
    JWT protected. Returns the download URL when completed.
    """
    try:
        # 1. Verify bot exists and belongs to the current user
        bot_query = select(Bot).where(Bot.id == bot_id, Bot.created_by == current_user.id)
        bot_res = await db.execute(bot_query)
        bot = bot_res.scalar_one_or_none()
        
        if not bot:
            return api_error_response(
                message="Bot not found or access denied.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 2. Create the ExportJob record in database (pending state)
        job = await export_job_repository.create_job(
            db,
            bot_id=bot_id,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )

        # 3. Generate the export CSV file
        try:
            job.status = ExportJobStatus.processing
            await db.commit()

            file_path = await csv_export_service.generate_export(
                db,
                bot_id=bot_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
            )

            job.file_path = file_path
            job.status = ExportJobStatus.completed
            await db.commit()
            await db.refresh(job)

        except Exception as export_err:
            job.status = ExportJobStatus.failed
            await db.commit()
            raise export_err

        # 4. Generate dynamic download URL
        # We replace the local upload directory name with URL path segment
        relative_path = file_path.replace("\\", "/").replace("uploads/", "")
        download_url = f"{request.base_url}uploads/{relative_path}"

        response_data = {
            "job_id": str(job.id),
            "status": job.status,
            "download_url": download_url,
            "created_at": job.created_at.isoformat(),
            "message": "Export completed successfully.",
        }

        return api_success_response(
            data=response_data,
            status_code=status.HTTP_201_CREATED,
        )


    except Exception as e:
        return api_error_response(
            message="An error occurred while running data export.",
            code="EXPORT_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ─────────────────────────────────────────────────────────────
# Analytics Snapshot Endpoints
# ─────────────────────────────────────────────────────────────

@router.get("/bots/{bot_id}/snapshots", status_code=status.HTTP_200_OK)
async def get_bot_snapshots(
    bot_id: uuid.UUID,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve daily analytics snapshots for a bot within an optional date range.
    Used for time-series chart rendering in the analytics dashboard.

    Query params:
        from_date: YYYY-MM-DD (defaults to 30 days ago)
        to_date:   YYYY-MM-DD (defaults to yesterday)
    """
    try:
        from datetime import date, timedelta

        # Verify ownership
        bot_q = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.created_by == current_user.id))
        bot = bot_q.scalars().first()
        if not bot:
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        today = date.today()
        end = date.fromisoformat(to_date) if to_date else today - timedelta(days=1)
        start = date.fromisoformat(from_date) if from_date else end - timedelta(days=29)

        snapshots = await snapshot_service.get_snapshot_range(
            bot_id=str(bot_id),
            start_date=start,
            end_date=end,
        )

        return api_success_response(data={"snapshots": snapshots, "count": len(snapshots)})

    except Exception as e:
        return api_error_response(
            message="Failed to retrieve snapshots.",
            code="SNAPSHOTS_FETCH_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/bots/{bot_id}/snapshots/generate", status_code=status.HTTP_202_ACCEPTED)
async def trigger_bot_snapshot(
    bot_id: uuid.UUID,
    date_str: Optional[str] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger snapshot generation for a bot (admin on-demand refresh).
    Dispatches a Celery task in background.
    """
    try:
        # Verify ownership
        bot_q = await db.execute(select(Bot).where(Bot.id == bot_id, Bot.created_by == current_user.id))
        bot = bot_q.scalars().first()
        if not bot:
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        from app.tasks.analytics import generate_bot_snapshot_on_demand
        generate_bot_snapshot_on_demand.delay(str(bot_id), date_str)

        return api_success_response(
            data={"message": "Snapshot generation queued.", "bot_id": str(bot_id), "date": date_str},
            status_code=status.HTTP_202_ACCEPTED,
        )

    except Exception as e:
        return api_error_response(
            message="Failed to queue snapshot generation.",
            code="SNAPSHOT_TRIGGER_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
