import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, EmailStr, field_validator
import re
from html import escape

class UserBase(BaseModel):
    """
    Shared attributes for user schemas.
    """
    email: EmailStr = Field(..., description="Unique email address of the user")
    name: Optional[str] = Field(None, max_length=100, description="Display name of the user")

    @field_validator("name", mode="before")
    @classmethod
    def sanitize_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        # Remove any HTML tags
        cleaned = re.sub(r'<[^>]*>', '', v)
        # Escape HTML entities
        return escape(cleaned.strip())

class UserCreate(UserBase):

    """
    Schema for creating a new user record.
    """
    password: str = Field(..., min_length=6, description="Raw password (minimum 6 characters)")

class UserResponse(UserBase):
    """
    Schema for returning user attributes in API responses.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

class UserLogin(BaseModel):
    """
    Schema for user credentials to authenticate and obtain tokens.
    """
    email: EmailStr = Field(..., description="Email address of the user")
    password: str = Field(..., description="Password of the user")


class TokenResponse(BaseModel):
    """
    Schema representing the issued access and refresh tokens along with user info.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

class TokenRefreshRequest(BaseModel):
    """
    Schema for token refresh request.
    """
    refresh_token: str = Field(..., description="The refresh token issued to the user")

class TokenRefreshResponse(BaseModel):
    """
    Schema representing the newly issued access and refresh tokens.
    """
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class UserProfileUpdate(BaseModel):
    name: str = Field(..., max_length=100, description="Updated display name")
    email: EmailStr = Field(..., description="Updated email address")

class UserPasswordUpdate(BaseModel):
    current_password: str = Field(..., min_length=6, description="Current password")
    new_password: str = Field(..., min_length=6, description="New password")
