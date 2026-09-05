import uuid
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

HostedModelVariant = Literal["finetuned", "base"]


class LLMSettingsResponse(BaseModel):
    llm_provider: str
    llm_api_url: str | None
    llm_api_key_set: bool
    llm_model: str | None
    llm_temperature: float
    llm_max_tokens: int
    narrative_paragraph_limit: int | None
    hosted_model_variant: HostedModelVariant

    model_config = {"from_attributes": True}


class LLMSettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_api_url: str | None = None
    llm_api_key: str | None = None   # empty string → clear saved key
    llm_model: str | None = None
    llm_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    llm_max_tokens: int | None = Field(default=None, ge=64, le=4096)
    # 0 → clear (back to the genre default of 2-4 paragraphs); 1-8 → pin the
    # quick-entry narrative to at most that many paragraphs. Same
    # omit-to-leave-unchanged convention as every other field here.
    narrative_paragraph_limit: int | None = Field(default=None, ge=0, le=8)
    # Not nullable/clearable like the fields above — omit to leave unchanged,
    # otherwise always a real value ("finetuned" is the default to fall back
    # to, not a "clear" sentinel).
    hosted_model_variant: HostedModelVariant | None = None


class ModelStatusResponse(BaseModel):
    """Whether this user's EFFECTIVE model backend is ready — powers the
    dashboard's "no model installed yet" banner on fresh self-hosted
    deployments, so the fix is offered by default instead of buried in the
    admin portal."""
    # False when the user configured their own provider (OpenAI key, custom
    # URL, …) — the platform's local model state is then irrelevant to them.
    uses_local_default: bool
    server_reachable: bool
    model_installed: bool
    model_name: str


class TestConnectionRequest(BaseModel):
    llm_provider: str
    llm_api_url: str | None = None
    llm_api_key: str | None = None  # omit to use saved key
    llm_model: str | None = None
    # Only consulted when llm_provider == "kobold" and llm_api_url is empty
    # (i.e. testing the platform hosted default, not a self-hosted server) —
    # picks which of the two models actually imported into Ollama to hit.
    hosted_model_variant: HostedModelVariant | None = None


class TestConnectionResponse(BaseModel):
    success: bool
    message: str


class EvaluationRequest(BaseModel):
    label: str = Field(..., max_length=100)
    sample_size: int = Field(default=10, ge=1, le=50)
    # Same override pattern as TestConnectionRequest — omit to use saved settings.
    llm_provider: str | None = None
    llm_api_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    # Shortcut for the Settings' Model Evaluation "quick compare" buttons —
    # when set, forces evaluation against the platform's hosted Ollama with
    # this variant specifically, ignoring the user's own saved provider
    # settings entirely (so comparing doesn't require changing and then
    # restoring your real config). Takes priority over llm_provider if both
    # are somehow given.
    hosted_model_variant: HostedModelVariant | None = None


class EvaluationResponse(BaseModel):
    id: uuid.UUID
    label: str
    sample_size: int
    avg_length: float
    avg_word_overlap: float
    # None on runs stored before the semantic metric existed.
    avg_semantic_similarity: float | None = None
    has_content_pct: float
    error_count: int
    created_at: datetime

    model_config = {"from_attributes": True}
