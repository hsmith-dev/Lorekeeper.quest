import uuid
from datetime import datetime
from pydantic import BaseModel


class SourceDocumentGMResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    title: str
    filename: str
    chunk_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SourceDocumentPartyResponse(SourceDocumentGMResponse):
    """A document a non-GM may see (its Visibility covers them). No GM-only
    fields today, so the same keys as the GM schema (access.project)."""


SourceDocumentResponse = SourceDocumentGMResponse
