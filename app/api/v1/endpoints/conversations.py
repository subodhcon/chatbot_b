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
        bots_query = select(Bot).where(Bot.created_by == current_user.id)
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
        bots = bots_res.scalars().all()
        bot_ids = [str(b.id) for b in bots]
        bot_name_map = {str(b.id): b.name for b in bots}

        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("conversations", settings.MONGODB_URL)
        if not mongo_client:
            return api_success_response(data=[])

        db_name = "chatbot"
        conv_coll = mongo_client[db_name]["conversations"]
        msg_coll = mongo_client[db_name]["messages"]

        cursor = conv_coll.find({"bot_id": {"$in": bot_ids}}).sort("updated_at", -1).skip(skip).limit(limit)
        conversations_data = []
        async for doc in cursor:
            conv = Conversation(doc)
            msg_count = await msg_coll.count_documents({"conversation_id": str(conv.id)})

            conversations_data.append({
                "id": str(conv.id),
                "bot_id": str(conv.bot_id),
                "bot_name": bot_name_map.get(str(conv.bot_id), "Unknown Bot"),
                "user_identifier": conv.user_identifier,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "messages_count": msg_count,
            })

        return api_success_response(data=conversations_data)

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
        # Verify ownership of the conversation's bot
        from app.core.config import settings
        from app.core.mongo import mongo_registry
        mongo_client = mongo_registry.get_client("conversations", settings.MONGODB_URL)
        if not mongo_client:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        conv_doc = await mongo_client["chatbot"]["conversations"].find_one({"_id": str(conversation_id)})
        if not conv_doc:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        conv = Conversation(conv_doc)

        bot_res = await db.execute(
            select(Bot).where(Bot.id == conv.bot_id).where(Bot.created_by == current_user.id)
        )
        bot = bot_res.scalar_one_or_none()
        if not bot:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        from app.services.message import message_service
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
