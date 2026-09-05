from pydantic import BaseModel, Field
from typing import Literal
import uuid
from datetime import datetime

_REASON_MAX_LENGTH = 500
_MESSAGE_MAX_LENGTH = 5000
_SUBJECT_MAX_LENGTH = 200
_CODE_MAX_LENGTH = 50
_NOTE_MAX_LENGTH = 200

PlanLiteral = Literal["byok", "hosted"]


class AdminUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime
    access_granted: bool
    access_source: str | None
    is_suspended: bool
    suspended_reason: str | None
    is_admin: bool
    subscription_plan: str | None
    subscription_status: str | None
    tokens_used_current_period: int | None
    tokens_included_per_period: int | None
    promo_code_used: str | None
    campaign_count: int
    journal_entry_count: int

    model_config = {"from_attributes": True}


class SuspendUserRequest(BaseModel):
    reason: str | None = Field(None, max_length=_REASON_MAX_LENGTH)


class SetUserAccessRequest(BaseModel):
    access_granted: bool
    # None leaves the existing plan (if any) untouched — only meaningful
    # when granting access; a plan on a not-access_granted account is
    # harmless but pointless, get_user_llm_config never reaches it.
    plan: PlanLiteral | None = None


class AdminMessageRequest(BaseModel):
    subject: str = Field(..., min_length=1, max_length=_SUBJECT_MAX_LENGTH)
    message: str = Field(..., min_length=1, max_length=_MESSAGE_MAX_LENGTH)


class PromoCodeRedemptionResponse(BaseModel):
    user_id: uuid.UUID
    user_email: str
    user_display_name: str
    redeemed_at: datetime


class PromoCodeAdminResponse(BaseModel):
    id: uuid.UUID
    code: str
    active: bool
    max_redemptions: int | None
    redemption_count: int
    expires_at: datetime | None
    note: str | None
    grants_plan: PlanLiteral
    created_at: datetime
    redemptions: list[PromoCodeRedemptionResponse]

    model_config = {"from_attributes": True}


class PromoCodeCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=_CODE_MAX_LENGTH)
    max_redemptions: int | None = Field(None, ge=1)
    expires_at: datetime | None = None
    note: str | None = Field(None, max_length=_NOTE_MAX_LENGTH)
    grants_plan: PlanLiteral = "byok"


class PromoCodeUpdateRequest(BaseModel):
    # All optional, only provided fields are changed (see admin.py's route —
    # uses model_dump(exclude_unset=True), so explicitly passing
    # expires_at: null clears it, while omitting the field entirely leaves
    # it untouched — exclude_unset distinguishes those two cases).
    active: bool | None = None
    max_redemptions: int | None = Field(None, ge=1)
    expires_at: datetime | None = None
    note: str | None = Field(None, max_length=_NOTE_MAX_LENGTH)
    grants_plan: PlanLiteral | None = None


class AppConfigResponse(BaseModel):
    open_access_mode: bool
    # Read-only status for the admin UI: whether Stripe env config is
    # complete enough for gated mode's billing to actually function.
    stripe_configured: bool

    model_config = {"from_attributes": True}


class AppConfigUpdateRequest(BaseModel):
    open_access_mode: bool


class ManagedModelStatus(BaseModel):
    # Which Ollama name this slot should exist under (settings.kobold_model /
    # kobold_base_model) and whether something is installed under it.
    name: str
    installed: bool
    # Where the System tab's install button gets it from.
    source: str


class ModelLibraryResponse(BaseModel):
    ollama_url: str
    ollama_reachable: bool
    ollama_error: str | None
    installed_models: list[str]
    finetuned: ManagedModelStatus
    base: ManagedModelStatus


class ModelInstallRequest(BaseModel):
    variant: Literal["finetuned", "base"] = "finetuned"


class LogsResponse(BaseModel):
    # Where these lines came from — "file" (the shared LOG_FILE all workers
    # append to) or "memory" (this worker's ring buffer, dev fallback).
    source: Literal["file", "memory"]
    lines: list[str]
