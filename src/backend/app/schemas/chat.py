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
    # Retrieval provenance for the transparency panel: cosine distance from
    # the dense retriever (None when only full-text matched) and which
    # retriever(s) surfaced it — "semantic" | "keyword" | "both".
    distance: float | None = None
    method: str | None = None


class RetrievalCandidate(BaseModel):
    """One journal entry either retriever surfaced, kept or not — the raw
    material of the 'how this answer was built' panel."""
    id: str
    shorthand: str
    session_date: str | None
    vector_distance: float | None
    lexical_rank: int | None
    rrf_score: float
    passed_gate: bool
    used: bool


class RetrievalDebug(BaseModel):
    """What actually happened between the user's question and the model's
    prompt — so groundedness is inspectable, not asserted."""
    query: str                      # the text retrieval actually ran with
    rewritten_from: str | None      # original message, when a rewrite was applied
    threshold: float                # vector-relevance gate in force
    candidates: list[RetrievalCandidate]
    system_prompt: str | None       # the exact system prompt the model saw


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
    # Full retrieval trace for the transparency panel. Optional so older
    # clients and non-campaign chats degrade cleanly.
    retrieval: RetrievalDebug | None = None


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
