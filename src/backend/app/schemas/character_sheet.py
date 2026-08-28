from typing import Literal, Any
from pydantic import BaseModel, Field, field_validator
import uuid
from datetime import datetime

_NAME_MAX_LENGTH = 200
_FIELD_TYPES = ("text", "number", "long_text", "list")


class TemplateField(BaseModel):
    key: str = Field(..., max_length=50)
    label: str = Field(..., max_length=100)
    type: Literal["text", "number", "long_text", "list"] = "text"


class TemplateCreate(BaseModel):
    campaign_id: uuid.UUID
    name: str = Field(..., max_length=100)
    fields: list[TemplateField] = Field(default_factory=list)

    @field_validator("fields")
    @classmethod
    def unique_keys(cls, v: list[TemplateField]) -> list[TemplateField]:
        keys = [f.key for f in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Field keys must be unique within a template.")
        return v


class TemplateUpdate(BaseModel):
    name: str | None = Field(None, max_length=100)
    fields: list[TemplateField] | None = None

    @field_validator("fields")
    @classmethod
    def unique_keys(cls, v: list[TemplateField] | None) -> list[TemplateField] | None:
        if v is None:
            return v
        keys = [f.key for f in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Field keys must be unique within a template.")
        return v


class TemplateResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    name: str
    fields: list[TemplateField]
    character_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CharacterSheetCreate(BaseModel):
    campaign_id: uuid.UUID
    template_id: uuid.UUID
    name: str = Field(..., max_length=_NAME_MAX_LENGTH)
    data: dict[str, Any] = Field(default_factory=dict)


class CharacterSheetUpdate(BaseModel):
    name: str | None = Field(None, max_length=_NAME_MAX_LENGTH)
    data: dict[str, Any] | None = None


class CharacterSheetResponse(BaseModel):
    id: uuid.UUID
    campaign_id: uuid.UUID
    template_id: uuid.UUID
    name: str
    data: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
