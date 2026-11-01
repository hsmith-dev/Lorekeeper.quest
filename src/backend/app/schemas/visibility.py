"""Bodies of `POST /api/campaigns/{campaign_id}/visibility` (E0-Access.9).

    {"items": [{"kind": "journal", "id": "...", "field": null}, ...], "value": "gm"}  ->  {"updated": 3}

`kind` must be a registered Visibility kind. `app.access.visibility`
registers each one here (`register_visibility_kind`) so an unknown kind is a
422 from validation, before the route runs. 1 to 500 items.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import Visibility
from app.schemas.sources import RecordRef

MAX_ITEMS = 500

# Filled by app.access.visibility.register_visibility_kind (schemas sit
# below access, so access writes here, never the reverse).
VISIBILITY_KINDS: set[str] = set()


class VisibilityItem(RecordRef):
    """One record (or one field of it) to change."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in VISIBILITY_KINDS:
            raise ValueError(f"unknown kind {value!r}; one of {sorted(VISIBILITY_KINDS)}")
        return value


class BulkVisibilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[VisibilityItem] = Field(min_length=1, max_length=MAX_ITEMS)
    value: Visibility


class BulkVisibilityResponse(BaseModel):
    """The number of distinct items written (unchanged values included)."""

    updated: int
