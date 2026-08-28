import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.character_sheet import CharacterSheetTemplate, CharacterSheet
from app.schemas.character_sheet import (
    TemplateCreate, TemplateUpdate, TemplateResponse,
    CharacterSheetCreate, CharacterSheetUpdate, CharacterSheetResponse,
)
from app.api.deps import get_current_user, get_campaign_with_access

router = APIRouter()

# Character sheets (and their templates) are shared campaign knowledge, same
# access rule as NPCs — any owner or member may read/write/delete, gated
# purely on campaign membership via get_campaign_with_access. See
# app/api/routes/npcs.py's _get_accessible_npc docstring for the reasoning.


async def _get_accessible_template(db: AsyncSession, template_id: uuid.UUID, user: User) -> CharacterSheetTemplate:
    template = await db.get(CharacterSheetTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    await get_campaign_with_access(db, template.campaign_id, user)
    return template


async def _get_accessible_sheet(db: AsyncSession, sheet_id: uuid.UUID, user: User) -> CharacterSheet:
    sheet = await db.get(CharacterSheet, sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Character not found")
    await get_campaign_with_access(db, sheet.campaign_id, user)
    return sheet


def _template_response(template: CharacterSheetTemplate, character_count: int = 0) -> TemplateResponse:
    return TemplateResponse.model_validate(template, from_attributes=True).model_copy(
        update={"character_count": character_count}
    )


# ── Templates ────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TemplateResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(CharacterSheetTemplate)
        .where(CharacterSheetTemplate.campaign_id == campaign_id)
        .order_by(CharacterSheetTemplate.name)
    )
    templates = result.scalars().all()
    if not templates:
        return []
    counts = dict(
        (await db.execute(
            select(CharacterSheet.template_id, func.count(CharacterSheet.id))
            .where(CharacterSheet.template_id.in_([t.id for t in templates]))
            .group_by(CharacterSheet.template_id)
        )).all()
    )
    return [_template_response(t, counts.get(t.id, 0)) for t in templates]


@router.post("/templates", response_model=TemplateResponse, status_code=201)
async def create_template(
    body: TemplateCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    template = CharacterSheetTemplate(
        campaign_id=body.campaign_id,
        created_by_user_id=user.id,
        name=body.name,
        fields=[f.model_dump() for f in body.fields],
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return _template_response(template)


@router.patch("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TemplateResponse:
    template = await _get_accessible_template(db, template_id, user)
    if body.name is not None:
        template.name = body.name
    if body.fields is not None:
        template.fields = [f.model_dump() for f in body.fields]
    await db.commit()
    await db.refresh(template)
    count = (
        await db.execute(select(func.count(CharacterSheet.id)).where(CharacterSheet.template_id == template.id))
    ).scalar() or 0
    return _template_response(template, count)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deleting a template cascades to every character sheet built from it
    (see character_sheets.template_id's ondelete="CASCADE") — the frontend is
    expected to warn using the list response's character_count before calling
    this, same pattern as removing a campaign member with delete_entries."""
    template = await _get_accessible_template(db, template_id, user)
    await db.delete(template)
    await db.commit()


# ── Character sheets ─────────────────────────────────────────────────────────

@router.get("/", response_model=list[CharacterSheetResponse])
async def list_character_sheets(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CharacterSheetResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(CharacterSheet).where(CharacterSheet.campaign_id == campaign_id).order_by(CharacterSheet.name)
    )
    return list(result.scalars().all())


@router.post("/", response_model=CharacterSheetResponse, status_code=201)
async def create_character_sheet(
    body: CharacterSheetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CharacterSheetResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    template = await db.get(CharacterSheetTemplate, body.template_id)
    if not template or template.campaign_id != body.campaign_id:
        raise HTTPException(status_code=404, detail="Template not found in this campaign")
    sheet = CharacterSheet(
        campaign_id=body.campaign_id,
        template_id=body.template_id,
        created_by_user_id=user.id,
        name=body.name,
        data=body.data,
    )
    db.add(sheet)
    await db.commit()
    await db.refresh(sheet)
    return sheet


@router.get("/{sheet_id}", response_model=CharacterSheetResponse)
async def get_character_sheet(
    sheet_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CharacterSheetResponse:
    return await _get_accessible_sheet(db, sheet_id, user)


@router.patch("/{sheet_id}", response_model=CharacterSheetResponse)
async def update_character_sheet(
    sheet_id: uuid.UUID,
    body: CharacterSheetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CharacterSheetResponse:
    sheet = await _get_accessible_sheet(db, sheet_id, user)
    if body.name is not None:
        sheet.name = body.name
    if body.data is not None:
        # Full replace, not a merge — the frontend always sends the complete
        # field-value map back (it has the template's full field list to
        # build it from), same convention as e.g. SessionPlan updates.
        sheet.data = body.data
    await db.commit()
    await db.refresh(sheet)
    return sheet


@router.delete("/{sheet_id}", status_code=204)
async def delete_character_sheet(
    sheet_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    sheet = await _get_accessible_sheet(db, sheet_id, user)
    await db.delete(sheet)
    await db.commit()
