import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.db.session import get_async_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message
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
        query = (
            select(Conversation, Bot.name.label("bot_name"))
            .join(Bot, Conversation.bot_id == Bot.id)
            .where(Bot.created_by == current_user.id)
        )
        
        if bot_id:
            try:
                bot_uuid = uuid.UUID(bot_id)
                query = query.where(Conversation.bot_id == bot_uuid)
            except ValueError:
                return api_error_response(
                    message="Invalid bot ID format.",
                    code="INVALID_BOT_ID",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        query = query.order_by(Conversation.updated_at.desc()).offset(skip).limit(limit)
        result = await db.execute(query)
        rows = result.all()

        conversations_data = []
        for row in rows:
            conv = row.Conversation
            # Fetch message count
            count_query = select(func.count()).select_from(Message).where(Message.conversation_id == conv.id)
            count_res = await db.execute(count_query)
            msg_count = count_res.scalar() or 0

            conversations_data.append({
                "id": str(conv.id),
                "bot_id": str(conv.bot_id),
                "bot_name": row.bot_name,
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
        query = (
            select(Conversation)
            .join(Bot, Conversation.bot_id == Bot.id)
            .where(Conversation.id == conversation_id)
            .where(Bot.created_by == current_user.id)
        )
        result = await db.execute(query)
        conv = result.scalar_one_or_none()

        if not conv:
            return api_error_response(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        msg_query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
        msg_result = await db.execute(msg_query)
        messages = msg_result.scalars().all()

        messages_data = [
            {
                "id": str(m.id),
                "conversation_id": str(m.conversation_id),
                "sender": m.sender,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
                "updated_at": m.updated_at.isoformat(),
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
