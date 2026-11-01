"""Members API schemas (E0-Access). E0-Access.12 adds invite / change Role /
remove; E0-Access.2 ships the caller's own Role (`GET /api/campaigns/{id}/me`)."""
import uuid
from typing import Literal

from pydantic import BaseModel


class CampaignRoleResponse(BaseModel):
    """The caller's Role in one Campaign. `role` is the ctx Role (Owner and
    Co-GM are both "gm"); `display_role` is the label the UI shows."""

    campaign_id: uuid.UUID
    role: Literal["gm", "player"]
    is_owner: bool
    display_role: Literal["Owner", "Co-GM", "Player"]
