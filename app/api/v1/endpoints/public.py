import uuid
import random
import asyncio
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, status, Body, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_async_db
from app.models.bot import Bot
from app.models.bot_config import BotConfig
from app.models.conversation import Conversation, Message
from app.models.feedback_rating import FeedbackRatingValue
from app.services.chat_agent import chat_agent_service
from app.services import conversation_service, message_service
from app.services.response_pipeline import ai_response_pipeline_service
from app.services.bot_config_resolver import bot_config_resolver
from app.repositories.feedback_rating import feedback_rating_repository
from app.core.responses import api_success_response, api_error_response
from app.utils.redis import get_redis
from app.utils.cache import get_cached_val, set_cached_val

router = APIRouter()
logger = logging.getLogger("app.api.public")


class ConversationInitRequest(BaseModel):
    bot_id: uuid.UUID
    browser_info: Optional[Dict[str, Any]] = None

class WidgetConversationCreateRequest(BaseModel):
    bot_id: uuid.UUID
    visitor_session_id: str

class WidgetErrorPayload(BaseModel):
    message: str
    stack: Optional[str] = None
    url: Optional[str] = None
    userAgent: Optional[str] = None
    bot_id: Optional[uuid.UUID] = None

@router.get("/bots/{bot_id}", status_code=status.HTTP_200_OK)
async def get_public_bot(
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    redis = Depends(get_redis),
):
    """
    Get public details of a bot to render guest guest chat screens.
    """
    try:
        cache_key = f"cache:public_bot:{bot_id}"
        cached = await get_cached_val(redis, cache_key)
        if cached is not None:
            return api_success_response(data=cached)

        query = (
            select(Bot, BotConfig)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Bot.id == bot_id)
            .where(Bot.is_active == True)
        )

        result = await db.execute(query)
        row = result.first()

        if not row:
            return api_error_response(
                message="Bot not found or inactive.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        bot, config = row
        bot_data = {
            "id": str(bot.id),
            "name": bot.name,
            "avatar_url": bot.avatar_url,
            "greeting_message": config.welcome_message or "Hello! How can I help you?",
            "tone": config.tone or "professional",
            "fallback_message": config.fallback_message or "I'm sorry, I am unable to assist with that query at the moment.",
            "extra_config": config.extra_config or {},
        }

        # Cache public bot settings for 2 minutes (ensures widgets sync changes quickly)
        await set_cached_val(redis, cache_key, bot_data, expire_seconds=120)


        return api_success_response(data=bot_data)


    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching public bot details.",
            code="PUBLIC_BOT_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def initialize_public_conversation(
    request: Request,
    payload: ConversationInitRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Start a new guest session for a bot. Saves welcome message dynamically.
    """
    try:
        bot_id = payload.bot_id
        
        # Capture browser details from payload and HTTP headers
        client_browser_info = payload.browser_info or {}
        user_agent = request.headers.get("user-agent", "")
        ip_address = request.client.host if request.client else ""
        
        combined_browser_info = {
            "user_agent": user_agent,
            "ip_address": ip_address,
            **client_browser_info
        }

        query = (
            select(Bot, BotConfig)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Bot.id == bot_id)
            .where(Bot.is_active == True)
        )
        result = await db.execute(query)
        row = result.first()

        if not row:
            return api_error_response(
                message="Bot not found or inactive.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        bot, config = row
        user_identifier = f"Guest #{random.randint(1000, 9999)}"

        # Create conversation
        conv = Conversation(
            id=uuid.uuid4(),
            bot_id=bot_id,
            user_identifier=user_identifier,
            browser_info=combined_browser_info,
        )
        db.add(conv)
        await db.commit()
        await db.refresh(conv)

        # Track conversation started event
        from app.services.analytics_tracking import analytics_tracking_service
        try:
            await analytics_tracking_service.track_conversation_started(
                db,
                bot_id=bot_id,
                conversation_id=conv.id,
            )
        except Exception as tracker_err:
            logger.error(f"Failed to track conversation started: {tracker_err}", exc_info=True)

        # Add initial welcome message from bot
        welcome_text = config.welcome_message or "Hello! How can I help you?"
        welcome_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            sender="bot",
            content=welcome_text,
        )
        db.add(welcome_msg)
        await db.commit()

        # Track welcome message (bot response)
        try:
            await analytics_tracking_service.track_bot_response(
                db,
                bot_id=bot_id,
                conversation_id=conv.id,
                response_length=len(welcome_text),
            )
        except Exception as tracker_err:
            logger.error(f"Failed to track bot response: {tracker_err}", exc_info=True)

        response_data = {
            "conversation_id": str(conv.id),
            "user_identifier": user_identifier,
            "welcome_message": welcome_text,
        }

        return api_success_response(data=response_data, status_code=status.HTTP_201_CREATED)

    except Exception as e:
        return api_error_response(
            message="An error occurred while initializing the session.",
            code="SESSION_INIT_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_public_message(
    conversation_id: uuid.UUID,
    content: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Send guest user message, run bot response service, and return bot response.
    """
    try:
        # Load conversation & associated bot configuration
        query = (
            select(Conversation, BotConfig)
            .join(Bot, Conversation.bot_id == Bot.id)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Conversation.id == conversation_id)
        )
        result = await db.execute(query)
        row = result.first()

        if not row:
            return api_error_response(
                message="Session not found.",
                code="SESSION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        conv, config = row

        # 1. Save guest message
        user_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            sender="user",
            content=content,
        )
        db.add(user_msg)
        await db.commit()

        # Track user message sent
        from app.services.analytics_tracking import analytics_tracking_service
        try:
            await analytics_tracking_service.track_message_sent(
                db,
                bot_id=conv.bot_id,
                conversation_id=conversation_id,
                sender="user",
                message_length=len(content),
            )
        except Exception as tracker_err:
            logger.error(f"Failed to track user message: {tracker_err}", exc_info=True)

        # Update conversation timestamp
        conv.updated_at = func.now()
        await db.commit()

        # 2. Load historical logs for context
        hist_query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        hist_res = await db.execute(hist_query)
        msg_rows = hist_res.scalars().all()

        history_payload = [
            {"role": "assistant" if m.sender == "bot" else "user", "content": m.content}
            for m in msg_rows
        ]

        # 3. Generate response using agent
        citations = []
        try:
            cfg = bot_config_resolver.resolve(config)
            pipeline_res = await ai_response_pipeline_service.generate_response(
                db=db,
                bot_id=conv.bot_id,
                user_question=content,
                chat_history=history_payload[:-1] if len(history_payload) > 1 else [],
                system_prompt=cfg.system_prompt,
                tone=cfg.tone,
                welcome_message=cfg.welcome_message,
                fallback_message=cfg.fallback_message,
                model_name=cfg.model_name,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                top_k=cfg.top_k,
                similarity_threshold=cfg.similarity_threshold,
                confidence_threshold=cfg.confidence_threshold,
            )
            bot_reply = pipeline_res["answer"]
            citations = pipeline_res.get("citations") or []
            escalation_eligible = pipeline_res.get("escalation_eligible", False)
        except Exception as pipeline_err:
            logger.warning(f"RAG pipeline failed, falling back to chat_agent_service: {pipeline_err}")
            bot_reply = await chat_agent_service.generate_response(
                system_prompt=config.system_prompt,
                tone=config.tone or "professional",
                fallback_message=config.fallback_message,
                history=history_payload,
            )
            citations = []
            escalation_eligible = True

        # 4. Save bot message
        bot_msg = Message(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            sender="bot",
            content=bot_reply,
        )
        db.add(bot_msg)
        await db.commit()
        await db.refresh(bot_msg)

        # Track bot response
        try:
            await analytics_tracking_service.track_bot_response(
                db,
                bot_id=conv.bot_id,
                conversation_id=conversation_id,
                response_length=len(bot_reply),
            )
        except Exception as tracker_err:
            logger.error(f"Failed to track bot response: {tracker_err}", exc_info=True)

        reply_data = {
            "id": str(bot_msg.id),
            "conversation_id": str(conversation_id),
            "sender": "bot",
            "content": bot_reply,
            "citations": citations,
            "escalation_eligible": escalation_eligible,
            "created_at": bot_msg.created_at.isoformat(),
        }

        return api_success_response(data=reply_data, status_code=status.HTTP_201_CREATED)

    except Exception as e:
        return api_error_response(
            message="An error occurred while generating chatbot reply.",
            code="REPLY_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/widgets/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_widget_placeholder_message(
    conversation_id: uuid.UUID,
    content: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_async_db),
):
    """
    Message handler foundation for the embeddable widget.
    Saves user message, creates a placeholder bot reply using the service layer, and stores both in DB.
    """
    try:
        # Load conversation & associated bot configuration
        query = (
            select(Conversation, BotConfig)
            .join(Bot, Conversation.bot_id == Bot.id)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Conversation.id == conversation_id)
        )
        result = await db.execute(query)
        row = result.first()

        if not row:
            return api_error_response(
                message="Session not found.",
                code="SESSION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        conv, config = row

        # 1. Save user message using service layer
        await message_service.save_user_message(
            db,
            conversation_id=conversation_id,
            content=content,
        )

        # Broadcast typing start
        from app.core.websocket import manager
        await manager.broadcast_json_to_session(
            str(conversation_id),
            {"event": "typing", "state": True}
        )

        # Load historical logs for context (includes the message we just saved)
        hist_query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        hist_res = await db.execute(hist_query)
        msg_rows = hist_res.scalars().all()

        history_payload = [
            {"role": "assistant" if m.sender == "bot" else "user", "content": m.content}
            for m in msg_rows
        ]

        # 2. Generate bot reply
        citations = []
        try:
            cfg = bot_config_resolver.resolve(config)
            pipeline_res = await ai_response_pipeline_service.generate_response(
                db=db,
                bot_id=conv.bot_id,
                user_question=content,
                chat_history=history_payload[:-1] if len(history_payload) > 1 else [],
                system_prompt=cfg.system_prompt,
                tone=cfg.tone,
                welcome_message=cfg.welcome_message,
                fallback_message=cfg.fallback_message,
                model_name=cfg.model_name,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                top_k=cfg.top_k,
                similarity_threshold=cfg.similarity_threshold,
                confidence_threshold=cfg.confidence_threshold,
            )
            bot_reply = pipeline_res["answer"]
            citations = pipeline_res.get("citations") or []
            escalation_eligible = pipeline_res.get("escalation_eligible", False)
        except Exception as pipeline_err:
            logger.warning(f"RAG pipeline failed for widget, falling back: {pipeline_err}")
            bot_reply = await chat_agent_service.generate_response(
                system_prompt=config.system_prompt,
                tone=config.tone or "professional",
                fallback_message=config.fallback_message,
                history=history_payload,
            )
            citations = []
            escalation_eligible = True

        # 3. Save assistant message using service layer
        bot_msg = await message_service.save_assistant_message(
            db,
            conversation_id=conversation_id,
            content=bot_reply,
        )

        # Broadcast typing stop
        await manager.broadcast_json_to_session(
            str(conversation_id),
            {"event": "typing", "state": False}
        )

        reply_data = {
            "id": str(bot_msg.id),
            "conversation_id": str(conversation_id),
            "sender": "bot",
            "content": bot_reply,
            "citations": citations,
            "escalation_eligible": escalation_eligible,
            "created_at": bot_msg.created_at.isoformat(),
        }

        return api_success_response(data=reply_data, status_code=status.HTTP_201_CREATED)

    except Exception as e:
        return api_error_response(
            message="An error occurred while creating message.",
            code="MESSAGE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/widgets/conversations", status_code=status.HTTP_201_CREATED)
async def create_widget_conversation(
    payload: WidgetConversationCreateRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Create a new widget conversation (WidgetSession) or return an existing active one,
    associated with the visitor_session_id.
    """
    try:
        session = await conversation_service.get_or_create_active_conversation(
            db,
            bot_id=payload.bot_id,
            visitor_session_id=payload.visitor_session_id,
        )
        return api_success_response(
            data={"conversation_id": str(session.id)},
            status_code=status.HTTP_201_CREATED,
        )
    except Exception as e:
        return api_error_response(
            message="An error occurred while initializing the widget conversation.",
            code="WIDGET_CONVERSATION_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/widgets/conversations/{conversation_id}", status_code=status.HTTP_200_OK)
async def get_widget_conversation_history(
    conversation_id: uuid.UUID,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Fetch details of a widget conversation session along with its paginated message history.
    """
    try:
        conv = await conversation_service.get_conversation(db, conversation_id=conversation_id)
        if not conv:
            return api_error_response(
                message="Conversation session not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        messages = await message_service.fetch_conversation_history(
            db,
            conversation_id=conversation_id,
            skip=skip,
            limit=limit,
        )

        response_data = {
            "conversation": {
                "id": str(conv.id),
                "bot_id": str(conv.bot_id),
                "visitor_session_id": conv.visitor_session_id,
                "status": conv.status,
                "started_at": conv.started_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
            },
            "messages": [
                {
                    "id": str(m.id),
                    "conversation_id": str(m.conversation_id),
                    "sender": m.sender,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ]
        }

        return api_success_response(data=response_data)
    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching conversation history.",
            code="HISTORY_FETCH_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class FeedbackSubmitRequest(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    rating: FeedbackRatingValue
    feedback_text: Optional[str] = None


@router.post("/messages/feedback", status_code=status.HTTP_201_CREATED)
async def submit_message_feedback(
    payload: FeedbackSubmitRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """
    Submit thumbs up / thumbs down feedback for a specific bot message.
    Stores the feedback in database and logs an analytics event.
    """
    try:
        # 1. Verify message and conversation exist
        msg_query = (
            select(Message)
            .where(Message.id == payload.message_id)
            .where(Message.conversation_id == payload.conversation_id)
        )
        msg_res = await db.execute(msg_query)
        message = msg_res.scalar_one_or_none()
        
        if not message:
            return api_error_response(
                message="Message or Conversation not found.",
                code="MESSAGE_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 2. Store feedback rating in the database
        feedback = await feedback_rating_repository.create_rating(
            db,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            rating=payload.rating,
            feedback_text=payload.feedback_text,
        )

        # 3. Track the feedback event in analytics
        from app.services.analytics_tracking import analytics_tracking_service
        try:
            conv_query = select(Conversation).where(Conversation.id == payload.conversation_id)
            conv_res = await db.execute(conv_query)
            conv = conv_res.scalar_one_or_none()
            if conv:
                await analytics_tracking_service.track_feedback_submitted(
                    db,
                    bot_id=conv.bot_id,
                    conversation_id=payload.conversation_id,
                    rating=1 if payload.rating == FeedbackRatingValue.thumbs_up else 0,
                    feedback_text=payload.feedback_text,
                    metadata={"message_id": str(payload.message_id), "rating_str": payload.rating.value}
                )
        except Exception as tracker_err:
            logger.error(f"Failed to track feedback analytics: {tracker_err}", exc_info=True)

        return api_success_response(
            data={
                "feedback_id": str(feedback.id),
                "message": "Feedback submitted successfully."
            },
            status_code=status.HTTP_201_CREATED,
        )


    except Exception as e:
        return api_error_response(
            message="An error occurred while submitting feedback.",
            code="FEEDBACK_SUBMISSION_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/errors", status_code=status.HTTP_200_OK)
async def report_widget_error(
    payload: WidgetErrorPayload,
):
    """
    Endpoint for embeddable chatbot widget to report frontend/widget errors.
    Integrates with the centralized error monitoring service.
    """
    try:
        from app.core.error_monitoring import error_monitor
        
        # Log/capture the error centrally
        error_monitor.capture_message(
            message=f"Widget Exception: {payload.message}",
            level="error",
            context={
                "stack": payload.stack,
                "url": payload.url,
                "userAgent": payload.userAgent,
                "bot_id": str(payload.bot_id) if payload.bot_id else None,
            },
            tags={"layer": "widget", "bot_id": str(payload.bot_id) if payload.bot_id else "unknown"}
        )
        return api_success_response(data={"status": "logged"})
    except Exception as e:
        logger.error(f"Failed to log widget error: {e}", exc_info=True)
        return api_error_response(
            message="Failed to log widget error",
            code="ERROR_LOGGING_FAILED",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


