"""Members API schemas (E0-Access). E0-Access.2 ships the caller's own Role
(`GET /api/campaigns/{id}/me`); E0-Access.12 the Members list and Role change."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class CampaignRoleResponse(BaseModel):
    """The caller's Role in one Campaign. `role` is the ctx Role (Owner and
    Co-GM are both "gm"); `display_role` is the label the UI shows."""

    campaign_id: uuid.UUID
    role: Literal["gm", "player"]
    is_owner: bool
    display_role: Literal["Owner", "Co-GM", "Player"]


class MemberResponse(BaseModel):
    """One row of `GET /api/campaigns/{id}/members` (E0-Access.12). The
    Owner's row comes first with `member_id: null` (the Owner has no grant
    row: nothing to change or remove); every Member row carries its grant id."""

    member_id: uuid.UUID | None
    user_id: uuid.UUID
    display_name: str
    role: Literal["owner", "co_gm", "player"]
    joined_at: datetime


class MemberRoleUpdate(BaseModel):
    """`PATCH /api/campaigns/{id}/members/{member_id}`: the stored Role to set.
    Ownership is not a Role a Member can be given."""

    role: Literal["co_gm", "player"]
