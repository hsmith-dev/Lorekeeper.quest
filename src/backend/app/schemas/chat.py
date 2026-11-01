from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.sources import Grounded, ResolvedSource, SourceRef

# GM and Party pairs (E0-Access.8), returned only through
# app.access.project_chat: a GM ctx gets the GM schema, anyone else the Party
# schema, which has no `shorthand` (sources, candidates) and no
# `system_prompt` (trace) at any depth, and whose `canon_sources` is always
# empty (source documents are GM-only). The Party models pin
# `extra="ignore"`: project_chat validates one GM-shaped body into them, and
# the GM keys (`shorthand`, `system_prompt`) must be dropped, never kept.
_PARTY = ConfigDict(extra="ignore")


class ChatMessage(BaseModel):
    """A chat message as GET /api/chat/sessions/{id} returns it. A message
    whose refs the reader can no longer all see is `redacted`: its content
    is a notice and its refs are empty."""
    role: str  # "user" | "assistant"
    content: str = Field(..., max_length=8000)
    refs: list[SourceRef] = []
    grounded: bool | None = None
    redacted: bool = False


class StoredChatMessage(BaseModel):
    """What `chat_sessions.messages[*]` holds: the text, the `SourceRef`s the
    reply drew on (never their titles or quotes) and the grounded flag
    (assistant turns). User turns are `{role, content, refs: []}`."""
    role: str
    content: str
    refs: list[SourceRef] = []
    grounded: bool | None = None

    def stored(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    campaign_id: str | None = None
    session_id: str | None = None  # if None, a new session is created


class JournalSourceParty(BaseModel):
    model_config = _PARTY
    id: str
    snippet: str
    session_date: str | None
    # Retrieval provenance for the transparency panel: cosine distance from
    # the dense retriever (None when only full-text matched) and which
    # retriever(s) surfaced it — "semantic" | "keyword" | "both".
    distance: float | None = None
    method: str | None = None


class JournalSource(JournalSourceParty):
    """The GM's source: the Party one plus the entry's Shorthand."""
    shorthand: str


class RetrievalCandidateParty(BaseModel):
    model_config = _PARTY
    """One journal entry either retriever surfaced, kept or not — the raw
    material of the 'how this answer was built' panel."""
    id: str
    session_date: str | None
    vector_distance: float | None
    lexical_rank: int | None
    rrf_score: float
    passed_gate: bool
    used: bool


class RetrievalCandidate(RetrievalCandidateParty):
    shorthand: str


class RetrievalDebugParty(BaseModel):
    model_config = _PARTY
    """What actually happened between the user's question and the model's
    prompt — so groundedness is inspectable, not asserted. No system prompt:
    it may carry the glossary and Shorthand."""
    query: str                      # the text retrieval actually ran with
    rewritten_from: str | None      # original message, when a rewrite was applied
    threshold: float                # vector-relevance gate in force
    candidates: list[RetrievalCandidateParty]


class RetrievalDebug(BaseModel):
    query: str
    rewritten_from: str | None
    threshold: float
    candidates: list[RetrievalCandidate]
    system_prompt: str | None       # the exact system prompt the model saw


# `grounded` (Grounded) is False when a campaign was selected but retrieval
# found nothing relevant (no journal entries or canon chunks passed the
# relevance threshold) — the reply is the model's own invention, not the
# campaign record, and the UI labels it accordingly. True whenever grounding
# context existed OR no campaign was selected.

class ChatMetaGM(Grounded):
    """The SSE `meta` event (everything known before generation starts)."""
    session_id: str
    sources: list[JournalSource] = []
    canon_sources: list[str] = []
    # Full retrieval trace for the transparency panel. Optional so older
    # clients and non-campaign chats degrade cleanly.
    retrieval: RetrievalDebug | None = None
    citations: list[ResolvedSource] = []


class ChatMetaParty(Grounded):
    model_config = _PARTY
    session_id: str
    sources: list[JournalSourceParty] = []
    canon_sources: list[str] = []
    retrieval: RetrievalDebugParty | None = None
    citations: list[ResolvedSource] = []

    @field_validator("canon_sources", mode="before")
    @classmethod
    def _no_canon(cls, value: Any) -> list[str]:
        return []  # source documents are GM-only


class ChatGMResponse(ChatMetaGM):
    reply: str


class ChatPartyResponse(ChatMetaParty):
    reply: str


ChatResponse = ChatGMResponse


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    campaign_id: str | None
    campaign_name: str | None
    message_count: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChatSessionDetailGM(ChatSessionSummary):
    messages: list[ChatMessage]


class ChatSessionDetailParty(ChatSessionSummary):
    messages: list[ChatMessage]


ChatSessionDetail = ChatSessionDetailGM
