import uuid
from datetime import datetime
from pydantic import BaseModel


class SourceDocumentResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    title: str
    filename: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
