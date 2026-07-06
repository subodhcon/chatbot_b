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
from app.models.conversation import Conversation, Message
from app.models.document import Document
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

        # 2. Conversations (24h)
        conv_24h_count = 0
        if bot_ids:
            since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
            conv_query = select(func.count(Conversation.id)).where(Conversation.bot_id.in_(bot_ids)).where(Conversation.created_at >= since_24h)
            conv_res = await db.execute(conv_query)
            conv_24h_count = conv_res.scalar() or 0

        # 3. Knowledge Docs Count
        doc_query = select(func.count(Document.id)).where(Document.created_by == current_user.id)
        doc_res = await db.execute(doc_query)
        knowledge_docs = doc_res.scalar() or 0

        # 4. Success Rate & Avg. Chat Time
        success_rate = 100.0
        total_sessions = 0
        avg_chat_time_seconds = 0

        if bot_ids:
            # Total sessions
            tot_query = select(func.count(Conversation.id)).where(Conversation.bot_id.in_(bot_ids))
            tot_res = await db.execute(tot_query)
            total_sessions = tot_res.scalar() or 0

            # Calculate Success Rate
            # To do this: check how many bot responses matched their bot's fallback message
            if total_sessions > 0:
                # Find all bot messages
                msg_query = (
                    select(Message.content, BotConfig.fallback_message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .join(Bot, Conversation.bot_id == Bot.id)
                    .join(BotConfig, Bot.id == BotConfig.bot_id)
                    .where(Bot.created_by == current_user.id)
                    .where(Message.sender == "bot")
                )
                msg_res = await db.execute(msg_query)
                bot_messages = msg_res.all()

                fallback_hits = 0
                total_bot_responses = len(bot_messages)

                for msg_content, fallback in bot_messages:
                    if fallback and msg_content == fallback:
                        fallback_hits += 1

                if total_bot_responses > 0:
                    success_rate = round(((total_bot_responses - fallback_hits) / total_bot_responses) * 100, 1)

            # Calculate Avg. Session Duration (time between first and last message in each conversation)
            # Fetch conversation start/end times
            time_query = (
                select(Conversation.id, func.min(Message.created_at), func.max(Message.created_at))
                .join(Message, Conversation.id == Message.conversation_id)
                .where(Conversation.bot_id.in_(bot_ids))
                .group_by(Conversation.id)
            )
            time_res = await db.execute(time_query)
            durations = time_res.all()

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


