from pydantic import BaseModel, model_validator
import uuid
from datetime import datetime
from app.db.models.tag import TagType


# GM and Party projections (E0-Access.4). Returned only through
# app.access.project: a GM ctx gets the GM schema, a Player or anon ctx the
# Party schema. Tags carry no GM field today, so the two have the same keys;
# for a non-GM the projection drops a hidden category (it renders as unset).

class TagCategoryGMRef(BaseModel):
    id: uuid.UUID
    name: str
    campaign_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TagCategoryPartyRef(BaseModel):
    id: uuid.UUID
    name: str
    campaign_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class TagGMResponse(BaseModel):
    id: uuid.UUID
    name: str
    tag_type: TagType | None = None
    # Mirrors Tag's actual `custom_category` relationship name so from_attributes
    # can populate it automatically wherever JournalEntry.tags is eager-loaded
    # with Tag.custom_category also eager-loaded — no manual construction needed.
    custom_category: TagCategoryGMRef | None = None

    model_config = {"from_attributes": True}


class TagPartyResponse(BaseModel):
    id: uuid.UUID
    name: str
    tag_type: TagType | None = None
    custom_category: TagCategoryPartyRef | None = None

    model_config = {"from_attributes": True}


class TagWithCountGMResponse(TagGMResponse):
    entry_count: int


class TagWithCountPartyResponse(TagPartyResponse):
    entry_count: int


# The pre-E0-Access.4 names are the GM schemas.
TagCategoryRef = TagCategoryGMRef
TagResponse = TagGMResponse
TagWithCount = TagWithCountGMResponse


class TagAttachRequest(BaseModel):
    """Manually attach a tag to a journal entry — exactly one of tag_type or
    custom_category_id must be set. get-or-create by (name, category)."""
    name: str
    tag_type: TagType | None = None
    custom_category_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def exactly_one_category(self) -> "TagAttachRequest":
        if bool(self.tag_type) == bool(self.custom_category_id):
            raise ValueError("Provide exactly one of tag_type or custom_category_id")
        return self
