import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    file_path: str
    file_size: int
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
