from datetime import datetime
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str = Field(..., max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    campaign_id: str | None = None
    session_id: str | None = None  # if None, a new session is created


class JournalSource(BaseModel):
    id: str
    snippet: str
    session_date: str | None
    shorthand: str


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[JournalSource] = []
    canon_sources: list[str] = []
    # False when a campaign was selected but retrieval found nothing relevant
    # (no journal entries or canon chunks passed the relevance threshold) —
    # the reply is the model's own invention, not the campaign record, and
    # the UI labels it accordingly. Deterministic, unlike prompt-level
    # "don't invent" instructions, which the creative fine-tune happily
    # ignores (verified live). True whenever grounding context existed OR no
    # campaign was selected (nothing claimed to be grounded in that case).
    grounded: bool = True


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    campaign_id: str | None
    campaign_name: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionDetail(ChatSessionSummary):
    messages: list[ChatMessage]
