import uuid
from sqlalchemy import String, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base, TimestampMixin


class CharacterSheetTemplate(Base, TimestampMixin):
    """A reusable, campaign-scoped field layout (e.g. "D&D 5e Character",
    "Cyberpunk Runner") that CharacterSheets are built from. This is a live
    schema, not a one-time stamp: editing `fields` here changes what every
    character sheet built from it shows going forward — adding a field shows
    up blank on existing sheets, removing one just stops surfacing whatever
    value was stored under that key (harmlessly orphaned in CharacterSheet.data,
    not deleted), so a whole party stays on one consistent sheet shape."""

    __tablename__ = "character_sheet_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Ordered list of {"key": str, "label": str, "type": "text"|"number"|"long_text"|"list"}.
    # `key` is the stable identifier stored in CharacterSheet.data — kept
    # constant even if `label` is edited later, so renaming a field in the UI
    # doesn't orphan every sheet's existing value for it.
    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    campaign: Mapped["Campaign"] = relationship()


class CharacterSheet(Base, TimestampMixin):
    """One built character: a name plus field values keyed against its
    template's `fields` (see CharacterSheetTemplate above). Campaign-scoped
    and shared campaign knowledge — same access rule as NpcEntry (any owner
    or member may read/write/delete; see app/api/routes/character_sheets.py).
    Deliberately separate from NpcEntry: NPCs are narrative roster entries
    (role/status/description for anyone in the story), this is a structured
    stat block a player fills in and grows over a campaign."""

    __tablename__ = "character_sheets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"))
    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("character_sheet_templates.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # {field_key: value} — value shape follows the field's declared type
    # (string for text/long_text, number for number, list[str] for list) but
    # isn't schema-validated server-side per-type, same trust level as any
    # other free-form JSON blob in this app (e.g. ChatSession.messages).
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    campaign: Mapped["Campaign"] = relationship()
    template: Mapped["CharacterSheetTemplate"] = relationship()
