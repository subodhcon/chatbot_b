import uuid
import json
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_async_db
from app.core.websocket import manager
from app.services import conversation_service, message_service
from app.services.response_pipeline import ai_response_pipeline_service
from app.services.chat_agent import chat_agent_service
from app.services.bot_config_resolver import bot_config_resolver
from app.core.security import decode_token
from app.repositories.user import user_repository
from app.models.bot import Bot
from app.models.bot_config import BotConfig
from app.models.conversation import Conversation

router = APIRouter()
logger = logging.getLogger("app.api.websocket")


@router.websocket("/ingestion/{bot_id}")
async def websocket_ingestion_endpoint(
    websocket: WebSocket,
    bot_id: str,
    token: str = Query(None),
    db: AsyncSession = Depends(get_async_db),
):
    """
    WebSocket endpoint for real-time knowledge ingestion status/progress updates.
    """
    # Accept the connection first so the handshake succeeds
    await websocket.accept()

    # 1. Validate UUID format
    try:
        bot_uuid = uuid.UUID(bot_id)
    except ValueError:
        logger.error(f"Invalid UUID format for bot_id in ingestion WS: {bot_id}")
        await websocket.send_json({"error": "invalid_bot_id", "message": "Invalid bot UUID format"})
        await websocket.close(code=4000)
        return

    # 2. Authenticate token
    if not token:
        logger.error(f"No token provided for ingestion WS: {bot_id}")
        await websocket.send_json({"error": "unauthorized", "message": "No token provided"})
        await websocket.close(code=4001)
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            logger.error("Invalid token type for ingestion WS")
            await websocket.send_json({"error": "unauthorized", "message": "Invalid token type"})
            await websocket.close(code=4002)
            return
        user_id = payload.get("sub")
        if not user_id:
            logger.error("No sub claim in token for ingestion WS")
            await websocket.send_json({"error": "unauthorized", "message": "Invalid token subject"})
            await websocket.close(code=4003)
            return
    except Exception as e:
        logger.error(f"Token decoding failed for ingestion WS: {e}")
        await websocket.send_json({"error": "unauthorized", "message": f"Token decoding failed: {str(e)}"})
        await websocket.close(code=4003)
        return

    user = await user_repository.get_user_by_id(db, id=user_id)
    if not user or not user.is_active:
        logger.error("User not found or inactive for ingestion WS")
        await websocket.send_json({"error": "unauthorized", "message": "User not found or inactive"})
        await websocket.close(code=4004)
        return

    # Verify bot exists and belongs to the user
    from app.services.bot import bot_service
    try:
        bot = await bot_service.get_bot(db, bot_uuid)
        if bot.created_by != user.id:
            logger.error(f"User {user.id} does not own bot {bot_id}")
            await websocket.send_json({"error": "forbidden", "message": "You do not own this bot"})
            await websocket.close(code=4005)
            return
    except Exception as e:
        logger.error(f"Bot not found or error loading bot: {e}")
        await websocket.send_json({"error": "not_found", "message": f"Bot not found or error: {str(e)}"})
        await websocket.close(code=4006)
        return

    client_channel = f"ingestion:{bot_id}"
    # Track the already accepted connection in manager
    if client_channel not in manager.active_connections:
        manager.active_connections[client_channel] = set()
    manager.active_connections[client_channel].add(websocket)

    try:
        while True:
            # Keep the connection alive
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, client_channel)
        logger.info(f"Ingestion WebSocket disconnected cleanly for bot {bot_id}")
    except Exception as e:
        logger.error(f"Error in Ingestion WebSocket session for bot {bot_id}: {e}")
        manager.disconnect(websocket, client_channel)




@router.websocket("/{conversation_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    db: AsyncSession = Depends(get_async_db),
):
    """
    WebSocket endpoint for real-time conversation message exchange and streaming responses.
    """
    await manager.connect(websocket, conversation_id)
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        logger.error(f"Invalid UUID format for conversation_id: {conversation_id}")
        await websocket.close(code=4000)
        return

    try:
        # Resolve bot_id dynamically for this conversation
        bot_id = await message_service._resolve_bot_id_for_conversation(db, conv_uuid)
        if not bot_id:
            logger.error(f"Conversation session not found for WebSocket: {conversation_id}")
            await websocket.close(code=4004)
            return

        # Load bot & associated configuration from SQL database using bot_id
        query = (
            select(Bot, BotConfig)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Bot.id == bot_id)
        )
        result = await db.execute(query)
        row = result.first()

        if not row:
            logger.error(f"Bot or configuration not found for WebSocket: {bot_id}")
            await websocket.close(code=4004)
            return

        bot, config = row

        # Resolve all bot config parameters once (safe defaults applied)
        cfg = bot_config_resolver.resolve(config)

        while True:
            # Receive text message from the websocket client
            raw_data = await websocket.receive_text()
            logger.info(f"Received websocket message on session {conversation_id}: {raw_data}")

            # Try parsing JSON or treat as raw content
            content = raw_data
            try:
                parsed = json.loads(raw_data)
                if isinstance(parsed, dict) and "content" in parsed:
                    content = parsed["content"]
            except json.JSONDecodeError:
                pass

            if not content.strip():
                continue

            # 1. Save user message to database
            await message_service.save_user_message(
                db,
                conversation_id=conv_uuid,
                content=content,
            )

            # 2. Broadcast typing start event
            await manager.broadcast_json_to_session(
                conversation_id,
                {"event": "typing", "state": True},
            )

            # 3. Broadcast stream start event
            await manager.broadcast_json_to_session(
                conversation_id,
                {"event": "stream_start"},
            )

            # Load historical logs for context (includes the message we just saved)
            msg_rows = await message_service.fetch_conversation_history(db, conversation_id=conv_uuid)

            history_payload = [
                {"role": "assistant" if m.sender == "bot" else "user", "content": m.content}
                for m in msg_rows
            ]

            accumulated_text = ""
            citations = []
            escalation_eligible = False

            try:
                # 4. Stream response from response pipeline
                async for chunk in ai_response_pipeline_service.generate_response_stream(
                    db=db,
                    bot_id=bot_id,
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
                ):
                    if "answer_chunk" in chunk:
                        text_delta = chunk["answer_chunk"]
                        accumulated_text += text_delta
                        await manager.broadcast_json_to_session(
                            conversation_id,
                            {"event": "stream_chunk", "text": text_delta},
                        )
                    else:
                        citations = chunk.get("citations") or []
                        escalation_eligible = chunk.get("escalation_eligible", False)
                        if chunk.get("answer"):
                            accumulated_text = chunk["answer"]
            except Exception as pipeline_err:
                logger.warning(f"RAG streaming pipeline failed, falling back: {pipeline_err}")
                # Fall back to legacy non-streamed chat_agent_service, but stream it word-by-word
                fallback_reply = await chat_agent_service.generate_response(
                    system_prompt=cfg.system_prompt,
                    tone=cfg.tone,
                    fallback_message=cfg.fallback_message,
                    history=history_payload,
                )
                accumulated_text = fallback_reply
                citations = []
                escalation_eligible = True
                # Stream the fallback reply
                words = fallback_reply.split(" ")
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words) - 1 else "")
                    await manager.broadcast_json_to_session(
                        conversation_id,
                        {"event": "stream_chunk", "text": chunk},
                    )
                    await asyncio.sleep(0.05)

            # 5. Broadcast stream end event with citations and escalation eligibility
            await manager.broadcast_json_to_session(
                conversation_id,
                {"event": "stream_end", "citations": citations, "escalation_eligible": escalation_eligible},
            )

            # 6. Save final compiled assistant response to database
            await message_service.save_assistant_message(
                db,
                conversation_id=conv_uuid,
                content=accumulated_text,
            )

            # 7. Broadcast typing stop event
            await manager.broadcast_json_to_session(
                conversation_id,
                {"event": "typing", "state": False},
            )

    except WebSocketDisconnect:
        manager.disconnect(websocket, conversation_id)
        logger.info(f"WebSocket disconnected cleanly for session {conversation_id}")
    except Exception as e:
        logger.error(f"Error in WebSocket session {conversation_id}: {e}")
        manager.disconnect(websocket, conversation_id)
