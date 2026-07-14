import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.db.session import get_async_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.conversation import Conversation
from app.models.bot import Bot
from app.models.bot_config import BotConfig
from app.schemas.conversation import ConversationResponse, MessageResponse
from app.core.responses import api_success_response, api_error_response

router = APIRouter()

@router.get("", status_code=status.HTTP_200_OK)
async def list_conversations(
    bot_id: str = None,
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve list of conversations/sessions for the authenticated user's bots.
    If bot_id is provided, filter by bot.
    """
    try:
        # User can only view conversations of bots owned by them
        bots_query = (
            select(Bot, BotConfig)
            .join(BotConfig, Bot.id == BotConfig.bot_id)
            .where(Bot.created_by == current_user.id)
        )
        if bot_id:
            try:
                bot_uuid = uuid.UUID(bot_id)
                bots_query = bots_query.where(Bot.id == bot_uuid)
            except ValueError:
                return api_error_response(
                    message="Invalid bot ID format.",
                    code="INVALID_BOT_ID",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        
        bots_res = await db.execute(bots_query)
        bots_rows = bots_res.all()
        bot_name_map = {str(r.Bot.id): r.Bot.name for r in bots_rows}

        import asyncio
        from datetime import datetime

        async def fetch_bot_conversations(bot, config):
            from app.core.config import settings
            from app.core.mongo import mongo_registry
            
            mongo_uri = None
            db_name = "chatbot"
            if config and config.use_custom_mongo and config.mongo_uri:
                mongo_uri = config.mongo_uri
                db_name = config.mongo_db_name or "chatbot"
            else:
                mongo_uri = settings.MONGODB_URL
                db_name = mongo_registry.get_database_name(settings.MONGODB_URL)
                
            if not mongo_uri:
                return []
                
            client = mongo_registry.get_client(str(bot.id), mongo_uri)
            if not client:
                return []
                
            mongo_db = client[db_name]
            conv_coll = mongo_db["conversations"]
            msg_coll = mongo_db["messages"]
            
            # Fetch conversations for this bot (sort/limit locally during aggregation)
            cursor = conv_coll.find({"bot_id": str(bot.id)}).sort("updated_at", -1).limit(skip + limit)
            bot_convs = []
            async for doc in cursor:
                conv = Conversation(doc)
                msg_count = await msg_coll.count_documents({"conversation_id": str(conv.id)})
                bot_convs.append({
                    "id": str(conv.id),
                    "bot_id": str(conv.bot_id),
                    "bot_name": bot_name_map.get(str(conv.bot_id), "Unknown Bot"),
                    "user_identifier": conv.user_identifier,
                    "created_at": conv.created_at.isoformat() if hasattr(conv.created_at, "isoformat") else str(conv.created_at),
                    "updated_at": conv.updated_at.isoformat() if hasattr(conv.updated_at, "isoformat") else str(conv.updated_at),
                    "updated_at_dt": conv.updated_at,
                    "messages_count": msg_count,
                })
            return bot_convs

        # Run queries in parallel
        tasks = [fetch_bot_conversations(row.Bot, row.BotConfig) for row in bots_rows]
        results = await asyncio.gather(*tasks)
        
        all_convs = []
        for r in results:
            all_convs.extend(r)
            
        # Sort globally by updated_at descending
        all_convs.sort(key=lambda x: x["updated_at_dt"], reverse=True)
        
        # Paginate results
        paginated_convs = all_convs[skip : skip + limit]
        
        # Strip datetime sorting key from responses
        for c in paginated_convs:
            c.pop("updated_at_dt", None)

        return api_success_response(data=paginated_convs)

    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching conversations.",
            code="CONVERSATION_LIST_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get("/{conversation_id}/messages", status_code=status.HTTP_200_OK)
async def list_conversation_messages(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve message transcripts for a specific session.
    """
    try:
        from app.services.message import message_service
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        
        # 1. Resolve bot_id dynamically for this conversation
        bot_id = await message_service._resolve_bot_id_for_conversation(db, conversation_id)
        if not bot_id:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 2. Verify ownership of the conversation's bot
        bot_res = await db.execute(
            select(Bot).where(Bot.id == bot_id).where(Bot.created_by == current_user.id)
        )
        bot = bot_res.scalar_one_or_none()
        if not bot:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        # 3. Retrieve conversation details from correct MongoDB instance
        from app.models.bot_config import BotConfig
        bot_config_res = await db.execute(
            select(BotConfig).where(BotConfig.bot_id == bot_id)
        )
        config = bot_config_res.scalars().first()

        mongo_uri = None
        db_name = "chatbot"
        if config and config.use_custom_mongo and config.mongo_uri:
            mongo_uri = config.mongo_uri
            db_name = config.mongo_db_name or "chatbot"
        else:
            mongo_uri = settings.MONGODB_URL
            db_name = mongo_registry.get_database_name(settings.MONGODB_URL)

        client = mongo_registry.get_client(str(bot_id), mongo_uri)
        conv_doc = None
        if client:
            conv_doc = await client[db_name]["conversations"].find_one({"_id": str(conversation_id)})

        if not conv_doc:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        
        # 4. Fetch chronological message list
        messages = await message_service.fetch_conversation_history(db, conversation_id=conversation_id)

        messages_data = [
            {
                "id": str(m.id),
                "conversation_id": str(m.conversation_id),
                "sender": m.sender,
                "content": m.content,
                "created_at": m.created_at.isoformat() if hasattr(m.created_at, "isoformat") else str(m.created_at),
                "updated_at": m.created_at.isoformat() if hasattr(m.created_at, "isoformat") else str(m.created_at),
            }
            for m in messages
        ]

        return api_success_response(data=messages_data)

    except Exception as e:
        return api_error_response(
            message="An error occurred while fetching message logs.",
            code="MESSAGE_FETCH_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
