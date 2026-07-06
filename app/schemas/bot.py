import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator
import re
from html import escape

def _clean_and_escape(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    # Strip HTML tags
    cleaned = re.sub(r'<[^>]*>', '', v)
    return escape(cleaned.strip())


# ---------------------------------------------------------------------------
# Config sub-schemas (embedded in bot response)
# ---------------------------------------------------------------------------


class BotConfigResponse(BaseModel):
    """
    Serialised view of a Bot's live configuration.
    Returned nested inside BotResponse.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    system_prompt: Optional[str] = None
    welcome_message: Optional[str] = None
    model_name: str
    temperature: float
    max_tokens: int
    top_k: int
    similarity_threshold: float
    is_streaming: bool
    fallback_message: Optional[str] = None
    tone: Optional[str] = None
    gdpr_enabled: bool
    extra_config: Optional[dict] = None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Bot request schemas
# ---------------------------------------------------------------------------

class BotCreate(BaseModel):
    """
    Request body for creating a new Bot.
    """
    name: str = Field(
        ...,
        min_length=1,
        max_length=150,
        description="Display name for the bot (required)",
    )
    avatar_url: Optional[str] = Field(
        None,
        description="URL of the bot avatar image",
    )
    is_active: bool = Field(
        True,
        description="Whether the bot is immediately active after creation",
    )

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: str) -> str:
        res = _clean_and_escape(v)
        if not res:
            raise ValueError("Bot name cannot be empty after sanitization.")
        return res


class BotUpdate(BaseModel):
    """
    Request body for partially updating a Bot.
    All fields are optional — only supplied fields are written.
    """
    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=150,
        description="New display name (triggers slug regeneration)",
    )
    avatar_url: Optional[str] = Field(
        None,
        description="Updated avatar URL",
    )
    is_active: Optional[bool] = Field(
        None,
        description="Toggle bot active status",
    )

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        res = _clean_and_escape(v)
        if not res:
            raise ValueError("Bot name cannot be empty after sanitization.")
        return res


# ---------------------------------------------------------------------------
# Bot response schema
# ---------------------------------------------------------------------------

class BotResponse(BaseModel):
    """
    Full Bot representation returned by the API.
    Includes the nested live configuration.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    avatar_url: Optional[str] = None
    is_active: bool
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Delete confirmation schema
# ---------------------------------------------------------------------------

class BotDeleteConfirm(BaseModel):
    """
    Request body for deleting a Bot.

    The caller must echo back the bot's exact name to confirm intent.
    This acts as a safeguard against accidental deletions — the same
    pattern used by GitHub repository deletions and Terraform destroy.
    """
    confirm_name: str = Field(
        ...,
        description="Must exactly match the bot's current name to confirm deletion",
    )


# ---------------------------------------------------------------------------
# Configuration update schemas
# ---------------------------------------------------------------------------

class BotConfigUpdateRequest(BaseModel):
    """
    Request body for updating a Bot's user-facing configuration.

    Only the three conversational settings are exposed here.
    Advanced LLM/RAG settings (temperature, top_k, etc.) are managed
    separately to avoid overwhelming the basic settings UI.
    """
    greeting_message: Optional[str] = Field(
        None,
        description="Opening message shown to users at the start of a conversation",
    )
    fallback_message: Optional[str] = Field(
        None,
        description="Message shown when the bot cannot answer a query",
    )
    tone: Optional[str] = Field(
        None,
        max_length=50,
        description="Conversational tone: professional, friendly, casual, formal",
    )
    gdpr_enabled: Optional[bool] = Field(
        None,
        description="Enable or disable GDPR compliance mode",
    )
    extra_config: Optional[dict] = Field(
        None,
        description="Freeform JSONB configuration bag containing widget styling details",
    )

    @field_validator("greeting_message", "fallback_message", "tone", mode="before")
    @classmethod
    def sanitize_fields(cls, v: Optional[str]) -> Optional[str]:
        return _clean_and_escape(v)


class BotVersionResponse(BaseModel):
    """
    Serialised view of an immutable BotVersion snapshot row.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    version_number: int
    snapshot_json: dict
    created_at: datetime


class BotConfigUpdateResponse(BaseModel):
    """
    Response returned after a config update with snapshot.
    Bundles the updated config state and the newly created version number.
    """
    config: BotConfigResponse
    version: BotVersionResponse


class BotVersionRestoreResponse(BaseModel):
    """
    Response returned after restoring a historical version.

    `restored_config` reflects the live config after the restore has been applied.
    `new_version` is the brand-new append-only version entry that records the
    restore event — the target version itself is never modified.
    """
    restored_config: BotConfigResponse
    new_version: BotVersionResponse
    restored_from_version_number: int
