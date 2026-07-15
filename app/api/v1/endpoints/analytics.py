import uuid
import re
import asyncio
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
    Retrieve live aggregated statistics for the logged-in user's admin dashboard
    by parallel-querying each bot's respective MongoDB instance.
    """
    try:
        cache_key = f"cache:analytics_summary:{current_user.id}"
        cached = await get_cached_val(redis, cache_key)
        if cached is not None:
            return api_success_response(data=cached)

        # 1. Fetch all user's bots and their configurations
        bot_configs_query = (
            select(Bot, BotConfig)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Bot.created_by == current_user.id)
        )
        bot_configs_res = await db.execute(bot_configs_query)
        bot_configs = bot_configs_res.all()
        active_bots = sum(1 for bot, _ in bot_configs if bot.is_active)

        # 2. Define parallel worker to query individual bot MongoDB counts
        async def fetch_bot_metrics(bot, config):
            from app.core.config import settings
            from app.core.mongo import mongo_registry
            
            # Resolve correct URI & db name for this bot
            mongo_uri = None
            db_name = "chatbot"
            if config and config.use_custom_mongo and config.mongo_uri:
                mongo_uri = config.mongo_uri
                db_name = config.mongo_db_name or "chatbot"
            else:
                mongo_uri = settings.MONGODB_URL
                db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
                
            if not mongo_uri:
                return {
                    "conv_24h": 0, "docs": 0, "total_sessions": 0, 
                    "fallback_hits": 0, "total_bot_responses": 0, 
                    "total_chat_time": 0, "chat_time_sessions": 0
                }
                
            client = mongo_registry.get_client(str(bot.id), mongo_uri)
            if not client:
                return {
                    "conv_24h": 0, "docs": 0, "total_sessions": 0, 
                    "fallback_hits": 0, "total_bot_responses": 0, 
                    "total_chat_time": 0, "chat_time_sessions": 0
                }
                
            mongo_db = client[db_name]
            
            # Fetch conversations count (24h)
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            conv_24h = await mongo_db["conversations"].count_documents({
                "bot_id": str(bot.id),
                "created_at": {"$gte": since_24h}
            })
            
            # Fetch knowledge documents count (always stored in the central MongoDB)
            central_client = mongo_registry.get_client("analytics_central", settings.MONGODB_URL)
            docs = 0
            if central_client:
                docs = await central_client["chatbot"]["knowledge_sources"].count_documents({
                    "bot_id": str(bot.id)
                })
            
            # Fetch total sessions
            total_sessions = await mongo_db["conversations"].count_documents({
                "bot_id": str(bot.id)
            })
            
            # Fetch fallback rate and chat duration metrics
            fallback_message = config.fallback_message or "I'm sorry, I am unable to assist with that query at the moment."
            conv_cursor = mongo_db["conversations"].find({"bot_id": str(bot.id)}, {"_id": 1})
            conv_ids = [c["_id"] async for c in conv_cursor]
            
            fallback_hits = 0
            total_bot_responses = 0
            total_chat_time = 0
            chat_time_sessions = 0
            
            if conv_ids:
                fallback_hits = await mongo_db["messages"].count_documents({
                    "conversation_id": {"$in": conv_ids},
                    "sender": "bot",
                    "content": {"$regex": re.escape(fallback_message), "$options": "i"}
                })
                total_bot_responses = await mongo_db["messages"].count_documents({
                    "conversation_id": {"$in": conv_ids},
                    "sender": "bot"
                })
                
                # Chat duration calculations using message times
                pipeline = [
                    {"$match": {"conversation_id": {"$in": conv_ids}}},
                    {"$group": {
                        "_id": "$conversation_id",
                        "min_time": {"$min": "$created_at"},
                        "max_time": {"$max": "$created_at"}
                    }}
                ]
                dur_cursor = mongo_db["messages"].aggregate(pipeline)
                async for d_doc in dur_cursor:
                    min_time = d_doc.get("min_time")
                    max_time = d_doc.get("max_time")
                    if min_time and max_time and min_time != max_time:
                        diff = (max_time - min_time).total_seconds()
                        if 0 < diff < 7200: # cap session at 2 hours max
                            total_chat_time += diff
                            chat_time_sessions += 1
                                
            return {
                "conv_24h": conv_24h,
                "docs": docs,
                "total_sessions": total_sessions,
                "fallback_hits": fallback_hits,
                "total_bot_responses": total_bot_responses,
                "total_chat_time": total_chat_time,
                "chat_time_sessions": chat_time_sessions
            }

        # 3. Trigger queries concurrently across all databases
        tasks = [fetch_bot_metrics(bot, config) for bot, config in bot_configs]
        metrics_results = await asyncio.gather(*tasks)

        # 4. Sum up all metric responses
        conv_24h_count = sum(m["conv_24h"] for m in metrics_results)
        knowledge_docs = sum(m["docs"] for m in metrics_results)
        total_sessions = sum(m["total_sessions"] for m in metrics_results)
        total_fallback_hits = sum(m["fallback_hits"] for m in metrics_results)
        total_bot_responses = sum(m["total_bot_responses"] for m in metrics_results)
        total_chat_time = sum(m["total_chat_time"] for m in metrics_results)
        chat_time_sessions = sum(m["chat_time_sessions"] for m in metrics_results)

        # 5. Compute rates
        success_rate = 100.0
        if total_bot_responses > 0:
            success_rate = round(((total_bot_responses - total_fallback_hits) / total_bot_responses) * 100, 1)

        avg_chat_time_seconds = 0
        if chat_time_sessions > 0:
            avg_chat_time_seconds = int(total_chat_time / chat_time_sessions)

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

        # Cache live summary for 2 minutes to save database lookup overhead
        await set_cached_val(redis, cache_key, summary_data, expire_seconds=120)

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
            job = await export_job_repository.update_async(
                db,
                db_obj=job,
                obj_in={"status": ExportJobStatus.processing.value}
            )

            file_path = await csv_export_service.generate_export(
                db,
                bot_id=bot_id,
                start_date=payload.start_date,
                end_date=payload.end_date,
            )

            job = await export_job_repository.update_async(
                db,
                db_obj=job,
                obj_in={
                    "status": ExportJobStatus.completed.value,
                    "file_path": file_path
                }
            )

        except Exception as export_err:
            await export_job_repository.update_async(
                db,
                db_obj=job,
                obj_in={"status": ExportJobStatus.failed.value}
            )
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
