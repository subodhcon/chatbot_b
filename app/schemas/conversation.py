import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import List, Optional

class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    sender: str
    content: str
    created_at: datetime
    updated_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    bot_name: Optional[str] = None
    user_identifier: str
    created_at: datetime
    updated_at: datetime
    messages_count: int = 0
