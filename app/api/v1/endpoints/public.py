import uuid
import random
import asyncio
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, status, Body, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from datetime import datetime
from app.db.session import get_async_db
from app.models.bot import Bot
from app.models.bot_config import BotConfig
from app.models.conversation import Conversation
from app.models.feedback_rating import FeedbackRatingValue
from app.services.chat_agent import chat_agent_service
from app.services import conversation_service, message_service
from app.services.response_pipeline import ai_response_pipeline_service
from app.services.bot_config_resolver import bot_config_resolver
from app.repositories.feedback_rating import feedback_rating_repository
from app.core.responses import api_success_response, api_error_response
from app.utils.redis import get_redis
from app.utils.cache import get_cached_val, set_cached_val
from app.services.rate_limiter import rate_limiter_service
from app.services.typing_indicator import typing_indicator_service

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

        # Create conversation in MongoDB dynamically using bot config
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        
        mongo_uri = None
        if config and config.use_custom_mongo:
            mongo_uri = config.mongo_uri
            db_name = config.mongo_db_name or mongo_registry.get_database_name(mongo_uri)
        else:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(mongo_uri)
            
        if not mongo_uri:
            raise ValueError("No MongoDB URL is configured for this bot.")
            
        mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
        if not mongo_client:
            raise RuntimeError("Failed to establish MongoDB client connection.")
            
        conv_id = str(uuid.uuid4())
        conv_doc = {
            "_id": conv_id,
            "bot_id": str(bot_id),
            "user_identifier": user_identifier,
            "browser_info": combined_browser_info,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        await mongo_client[db_name]["conversations"].insert_one(conv_doc)
        conv = Conversation(conv_doc)

        # Cache conversation mapping in Redis
        try:
            from app.utils.redis import get_redis
            redis_gen = get_redis()
            redis_client = await redis_gen.__anext__()
            if redis_client and not getattr(redis_client, "is_mock", False):
                await redis_client.set(f"cache:conv_bot:{conv_id}", str(bot_id), ex=86400)
        except Exception as cache_err:
            logger.warning(f"Failed to cache conversation mapping in Redis: {cache_err}")

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
        from app.services.message import message_service
        await message_service.save_assistant_message(
            db,
            conversation_id=conv.id,
            content=welcome_text,
        )


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
        # Resolve bot_id dynamically for this conversation
        from app.services.message import message_service
        bot_id = await message_service._resolve_bot_id_for_conversation(db, conversation_id)
        if not bot_id:
            return api_error_response(
                message="Session not found.",
                code="SESSION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
            
        config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        config = config_res.scalars().first()

        # Connect to bot's MongoDB
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_uri = None
        if config and config.use_custom_mongo:
            mongo_uri = config.mongo_uri
            db_name = config.mongo_db_name or mongo_registry.get_database_name(mongo_uri)
        else:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(mongo_uri)
            
        if not mongo_uri:
            raise ValueError("No MongoDB URL is configured for this bot.")
            
        mongo_client = mongo_registry.get_client(str(bot_id), mongo_uri)
        conv_doc = await mongo_client[db_name]["conversations"].find_one({"_id": str(conversation_id)})
        if not conv_doc:
            return api_error_response(
                message="Session not found.",
                code="SESSION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        conv = Conversation(conv_doc)

        # --- Rate Limit Check ---
        ip_address = ""
        is_allowed, retry_after = await rate_limiter_service.check_and_record(
            conversation_id=str(conversation_id),
            bot_id=str(conv.bot_id),
            ip_address=ip_address,
            visitor_identifier=conv_doc.get("user_identifier", ""),
        )
        if not is_allowed:
            return api_error_response(
                message=f"Too many messages. Please wait {retry_after} seconds before sending again.",
                code="RATE_LIMIT_EXCEEDED",
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # 1. Save guest message using service
        from app.services.message import message_service
        user_msg = await message_service.save_user_message(
            db,
            conversation_id=conversation_id,
            content=content,
        )

        # Update conversation timestamp in MongoDB
        await mongo_client[db_name]["conversations"].update_one(
            {"_id": str(conversation_id)},
            {"$set": {"updated_at": datetime.utcnow()}}
        )

        # --- Set Typing Indicator (bot is generating response) ---
        await typing_indicator_service.set_typing(
            conversation_id=str(conversation_id),
            bot_id=str(conv.bot_id),
        )

        # 2. Load historical logs for context
        msg_rows = await message_service.fetch_conversation_history(db, conversation_id=conversation_id)

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
        bot_msg = await message_service.save_assistant_message(
            db,
            conversation_id=conversation_id,
            content=bot_reply,
        )

        # --- Clear Typing Indicator ---
        await typing_indicator_service.clear_typing(str(conversation_id))

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
        # Always clear typing on error too
        try:
            await typing_indicator_service.clear_typing(str(conversation_id))
        except Exception:
            pass
        return api_error_response(
            message="An error occurred while generating chatbot reply.",
            code="REPLY_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/conversations/{conversation_id}/typing", status_code=status.HTTP_200_OK)
async def get_typing_status(conversation_id: uuid.UUID):
    """
    Poll whether the bot is currently generating a response for this conversation.
    Widget can call this every 500ms to show/hide the typing indicator.

    Returns: { "is_typing": bool, "started_at": str | null }
    """
    try:
        result = await typing_indicator_service.get_status(str(conversation_id))
        return api_success_response(data=result)
    except Exception as e:
        return api_error_response(
            message="Failed to get typing status.",
            code="TYPING_STATUS_FAILED",
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
        # Load conversation from MongoDB & associated bot configuration
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("public_endpoint", settings.MONGODB_URL)
        db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
        conv_doc = await mongo_client[db_name]["widget_sessions"].find_one({"_id": str(conversation_id)})
        if not conv_doc:
            return api_error_response(
                message="Session not found.",
                code="SESSION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        conv = Conversation(conv_doc)

        config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == conv.bot_id)
        )
        config = config_res.scalars().first()

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
        msg_rows = await message_service.fetch_conversation_history(db, conversation_id=conversation_id)

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
    Scans all bot MongoDB configurations in parallel to find the session.
    """
    import asyncio
    from sqlalchemy import select
    from app.models.bot_config import BotConfig
    from app.core.mongo import mongo_registry
    from app.core.config import settings

    try:
        # --- Step 1: Find the widget session by scanning all bot MongoDB configs in parallel ---
        conv_doc = None
        found_bot_id = None
        found_client = None
        found_db_name = None

        async def search_in_mongo(bot_id_str, mongo_uri, db_name_str):
            """Search for conversation_id in a specific MongoDB."""
            try:
                client = mongo_registry.get_client(bot_id_str, mongo_uri)
                if not client:
                    return None, None, None, None
                doc = await asyncio.wait_for(
                    client[db_name_str]["widget_sessions"].find_one({"_id": str(conversation_id)}),
                    timeout=3.0
                )
                if doc:
                    return doc, bot_id_str, client, db_name_str
            except Exception:
                pass
            return None, None, None, None

        # Build search tasks for all bot configs
        bot_configs_res = await db.execute(select(BotConfig))
        bot_configs = bot_configs_res.scalars().all()

        tasks = []
        for config in bot_configs:
            if config.use_custom_mongo and config.mongo_uri:
                mongo_uri = config.mongo_uri
                db_name_str = config.mongo_db_name or mongo_registry.get_database_name(mongo_uri)
            elif settings.MONGODB_URL and "localhost" not in settings.MONGODB_URL:
                mongo_uri = settings.MONGODB_URL
                db_name_str = mongo_registry.get_database_name(settings.MONGODB_URL)
            else:
                continue
            tasks.append(search_in_mongo(str(config.bot_id), mongo_uri, db_name_str))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, tuple) and result[0] is not None:
                    conv_doc, found_bot_id, found_client, found_db_name = result
                    break

        if not conv_doc:
            return api_error_response(
                message="Conversation session not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        from app.models.widget_session import WidgetSession
        conv = WidgetSession(conv_doc)

        # --- Step 2: Fetch messages from the same MongoDB ---
        messages = []
        try:
            msg_cursor = found_client[found_db_name]["messages"].find(
                {"conversation_id": str(conversation_id)}
            ).sort("created_at", 1).skip(skip).limit(limit)
            async for doc in msg_cursor:
                from app.services.message import MongoMessageWrapper
                messages.append(MongoMessageWrapper(doc))
        except Exception as msg_err:
            logger.warning(f"Failed to fetch messages for conversation {conversation_id}: {msg_err}")

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
        # 1. Verify message and conversation exist in MongoDB
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("public", settings.MONGODB_URL)
        db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
        conv_doc = None
        if mongo_client:
            conv_doc = await mongo_client[db_name]["conversations"].find_one({"_id": str(payload.conversation_id)})
        if not conv_doc:
            return api_error_response(
                message="Message or Conversation not found.",
                code="MESSAGE_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        conv = Conversation(conv_doc)
            
        mongo_client = mongo_registry.get_client("public", settings.MONGODB_URL)
        db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
        msg_found = False
        if mongo_client:
            messages_coll = mongo_client[db_name]["messages"]
            doc = await messages_coll.find_one({"_id": str(payload.message_id), "conversation_id": str(payload.conversation_id)})
            if doc:
                msg_found = True
                
        if not msg_found:
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


