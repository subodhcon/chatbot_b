import uuid
from typing import Any, List
from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.bot import Bot
from app.models.bot_manager import BotManager
from app.repositories.user import user_repository
from app.core.security import hash_password
from app.core.responses import api_success_response, api_error_response
from pydantic import BaseModel, EmailStr, Field

router = APIRouter()

# Schema for creating user via Superadmin
class SuperadminUserCreate(BaseModel):
    email: EmailStr
    name: str = Field(..., max_length=100)
    password: str = Field(..., min_length=6)
    role: str = Field("user", max_length=50)

# Schema for updating user via Superadmin
from typing import Optional
class SuperadminUserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = Field(None, max_length=100)
    password: Optional[str] = Field(None, min_length=6)
    role: Optional[str] = Field(None, max_length=50)

# Helper function to check if current user is superadmin
def verify_superadmin(current_user: User = Depends(get_current_user)):
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superadmin is authorized to perform this action."
        )
    return current_user

# 1. GET /api/v1/users — list all users and their assigned bots
@router.get("", status_code=status.HTTP_200_OK)
async def list_users(
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        # Fetch all users
        result = await db.execute(select(User))
        users = result.scalars().all()
        
        # Prepare list of users with their assigned bots
        users_list = []
        for u in users:
            # Fetch assigned bot ids/names for this user
            bot_stmt = select(Bot).join(BotManager).where(BotManager.user_id == u.id)
            bot_res = await db.execute(bot_stmt)
            assigned_bots = bot_res.scalars().all()
            
            users_list.append({
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "role": u.role,
                "is_active": u.is_active,
                "created_at": u.created_at.isoformat(),
                "assigned_bots": [{"id": str(b.id), "name": b.name} for b in assigned_bots]
            })
            
        return api_success_response(data=users_list)
    except Exception as e:
        return api_error_response(
            message="Failed to fetch users.",
            code="FETCH_USERS_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# 2. POST /api/v1/users — create a new user
@router.post("", status_code=status.HTTP_201_CREATED)
async def create_user(
    user_in: SuperadminUserCreate,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        # Check if email exists
        existing_user = await user_repository.get_user_by_email(db, email=user_in.email)
        if existing_user:
            return api_error_response(
                message="Email already registered.",
                code="DUPLICATE_EMAIL",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            
        hashed_pw = hash_password(user_in.password)
        user_data = {
            "email": user_in.email,
            "name": user_in.name,
            "password_hash": hashed_pw,
            "role": user_in.role,
            "is_active": True
        }
        new_user = await user_repository.create_user(db, obj_in=user_data)
        
        return api_success_response(
            data={
                "id": str(new_user.id),
                "name": new_user.name,
                "email": new_user.email,
                "role": new_user.role,
                "is_active": new_user.is_active
            },
            status_code=status.HTTP_201_CREATED
        )
    except Exception as e:
        return api_error_response(
            message="Failed to create user.",
            code="CREATE_USER_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# 3. DELETE /api/v1/users/{user_id} — soft delete/deactivate a user
@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        user = await user_repository.get_user_by_id(db, id=user_id)
        if not user:
            return api_error_response(
                message="User not found.",
                code="USER_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND
            )
            
        # Deactivate
        user.is_active = False
        await db.commit()
        
        return api_success_response(
            data={"id": str(user_id), "deactivated": True, "is_active": False}
        )
    except Exception as e:
        return api_error_response(
            message="Failed to deactivate user.",
            code="DEACTIVATE_USER_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# PATCH /api/v1/users/{user_id}/status — toggle activation status
@router.patch("/{user_id}/status", status_code=status.HTTP_200_OK)
async def toggle_user_status(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        user = await user_repository.get_user_by_id(db, id=user_id)
        if not user:
            return api_error_response(
                message="User not found.",
                code="USER_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND
            )
            
        if user.id == admin_user.id:
            return api_error_response(
                message="You cannot deactivate your own account.",
                code="BAD_REQUEST",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            
        # Toggle status
        user.is_active = not user.is_active
        await db.commit()
        
        return api_success_response(
            data={"id": str(user_id), "is_active": user.is_active}
        )
    except Exception as e:
        return api_error_response(
            message="Failed to update user status.",
            code="STATUS_UPDATE_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# PUT /api/v1/users/{user_id} — edit user details and reset password
@router.put("/{user_id}", status_code=status.HTTP_200_OK)
async def update_user_details(
    user_id: uuid.UUID,
    user_in: SuperadminUserUpdate,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        user = await user_repository.get_user_by_id(db, id=user_id)
        if not user:
            return api_error_response(
                message="User not found.",
                code="USER_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND
            )
            
        # If updating email, check for duplicate
        if user_in.email and user_in.email != user.email:
            existing_user = await user_repository.get_user_by_email(db, email=user_in.email)
            if existing_user:
                return api_error_response(
                    message="Email already registered by another user.",
                    code="DUPLICATE_EMAIL",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            user.email = user_in.email
            
        if user_in.name is not None:
            user.name = user_in.name
            
        if user_in.role is not None:
            # Prevent self role-demotion from superadmin
            if user.id == admin_user.id and user_in.role != "superadmin":
                return api_error_response(
                    message="You cannot change your own superadmin role.",
                    code="BAD_REQUEST",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
            user.role = user_in.role
            
        if user_in.password:
            user.password_hash = hash_password(user_in.password)
            
        await db.commit()
        await db.refresh(user)
        
        return api_success_response(
            data={
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "is_active": user.is_active
            }
        )
    except Exception as e:
        return api_error_response(
            message="Failed to update user.",
            code="UPDATE_USER_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# 4. POST /api/v1/users/{user_id}/bots/{bot_id} — assign a bot to a user
@router.post("/{user_id}/bots/{bot_id}", status_code=status.HTTP_200_OK)
async def assign_bot(
    user_id: uuid.UUID,
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        # Check if user and bot exist
        user = await user_repository.get_user_by_id(db, id=user_id)
        if not user:
            return api_error_response(
                message="User not found.",
                code="USER_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND
            )
            
        bot_res = await db.execute(select(Bot).where(Bot.id == bot_id))
        bot = bot_res.scalars().first()
        if not bot:
            return api_error_response(
                message="Bot not found.",
                code="BOT_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND
            )
            
        # Check if already assigned
        existing = await db.execute(
            select(BotManager).where(BotManager.user_id == user_id, BotManager.bot_id == bot_id)
        )
        if existing.scalars().first():
            return api_success_response(data={"message": "User is already assigned to this bot."})
            
        # Create assignment
        new_manager = BotManager(
            id=uuid.uuid4(),
            user_id=user_id,
            bot_id=bot_id,
            role="editor"
        )
        db.add(new_manager)
        await db.commit()
        
        return api_success_response(
            data={"user_id": str(user_id), "bot_id": str(bot_id), "assigned": True}
        )
    except Exception as e:
        return api_error_response(
            message="Failed to assign bot.",
            code="ASSIGN_BOT_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

# 5. DELETE /api/v1/users/{user_id}/bots/{bot_id} — unassign a bot from a user
@router.delete("/{user_id}/bots/{bot_id}", status_code=status.HTTP_200_OK)
async def unassign_bot(
    user_id: uuid.UUID,
    bot_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(verify_superadmin)
):
    try:
        stmt = delete(BotManager).where(BotManager.user_id == user_id, BotManager.bot_id == bot_id)
        await db.execute(stmt)
        await db.commit()
        
        return api_success_response(
            data={"user_id": str(user_id), "bot_id": str(bot_id), "unassigned": True}
        )
    except Exception as e:
        return api_error_response(
            message="Failed to unassign bot.",
            code="UNASSIGN_BOT_FAILED",
            details=str(e),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
