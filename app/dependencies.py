from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db, get_async_db
from app.core.security import decode_token
from app.models.user import User
from app.repositories.user import user_repository

reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)

async def get_current_user(
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(reusable_oauth2)
) -> User:
    """
    Dependency to validate the access token and retrieve the current user.
    """
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
        
    user = await user_repository.get_user_by_id(db, id=user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Inactive user",
        )
    return user

from sqlalchemy import select
from app.models.bot import Bot
from app.models.bot_manager import BotManager

async def has_bot_access(db: AsyncSession, user: User, bot_id) -> bool:
    """
    Checks if the user has access to a specific bot.
    - superadmin: has access to all bots.
    - bot creator: has access to the bot they created.
    - bot manager: has access if mapped in the bot_managers table.
    """
    if user.role == "superadmin":
        return True

    import uuid
    try:
        bot_uuid = uuid.UUID(str(bot_id))
        user_uuid = uuid.UUID(str(user.id))
    except ValueError:
        return False

    # Check if user is the creator
    stmt_creator = select(Bot).where(Bot.id == bot_uuid, Bot.created_by == user_uuid)
    res_creator = await db.execute(stmt_creator)
    if res_creator.scalar_one_or_none():
        return True

    # Check if user is an assigned manager
    stmt_manager = select(BotManager).where(
        BotManager.bot_id == bot_uuid,
        BotManager.user_id == user_uuid
    )
    res_manager = await db.execute(stmt_manager)
    if res_manager.scalar_one_or_none():
        return True

    return False

# Re-exporting database and authentication dependencies
__all__ = ["get_db", "get_async_db", "get_current_user", "has_bot_access"]

