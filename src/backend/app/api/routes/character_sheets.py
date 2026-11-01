import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.access import (
    CampaignContext, check_create, ctx_for_request, not_found, project, project_all, require_campaign,
    require_campaign_for, scoped_get, scoped_select,
)
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.character_sheet import CharacterSheetTemplate, CharacterSheet
from app.schemas.character_sheet import (
    TemplateCreate, TemplateUpdate, TemplateGMResponse,
    CharacterSheetCreate, CharacterSheetUpdate, CharacterSheetGMResponse,
)
from app.api.deps import get_current_user

router = APIRouter()

# Character sheets (and their templates) are shared campaign knowledge: any
# owner or member may read/write/delete the ones they can see (Player write
# rules arrive with E0-Access.6). Every row comes from scoped_select /
# scoped_get and every body goes through access.project (E0-Access.4): a
# sheet the caller may not see (visibility gm, or another user's private
# one) is absent from lists and counts and is the one 404 by id.
_GM_OR_PARTY = "GM: the GM schema; Player or member preview: the Party schema."
_template_ctx = require_campaign_for(CharacterSheetTemplate, "template_id")
_sheet_ctx = require_campaign_for(CharacterSheet, "sheet_id")


async def _visible_sheet_counts(db: AsyncSession, ctx: CampaignContext, template_ids: list[uuid.UUID]) -> dict:
    """{template_id: number of its sheets ctx may see}."""
    if not template_ids:
        return {}
    stmt = (
        scoped_select(CharacterSheet, ctx)
        .where(CharacterSheet.template_id.in_(template_ids))
        .with_only_columns(CharacterSheet.template_id, func.count(CharacterSheet.id))
        .group_by(CharacterSheet.template_id)
    )
    return dict((await db.execute(stmt)).all())


async def _project_template(db: AsyncSession, template: CharacterSheetTemplate, ctx: CampaignContext):
    counts = await _visible_sheet_counts(db, ctx, [template.id])
    return project(template, ctx, extra={"character_count": counts.get(template.id, 0)})


# ── Templates ────────────────────────────────────────────────────────────────

@router.get("/templates", response_model=None,
            responses={200: {"model": list[TemplateGMResponse], "description": _GM_OR_PARTY}})
async def list_templates(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(scoped_select(CharacterSheetTemplate, ctx).order_by(CharacterSheetTemplate.name))
    templates = result.scalars().all()
    if not templates:
        return []
    counts = await _visible_sheet_counts(db, ctx, [t.id for t in templates])
    return await project_all(db, templates, ctx, extra=lambda t: {"character_count": counts.get(t.id, 0)})


@router.post("/templates", response_model=None, status_code=201,
             responses={201: {"model": TemplateGMResponse, "description": _GM_OR_PARTY}})
async def create_template(
    request: Request,
    body: TemplateCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    template = CharacterSheetTemplate(
        campaign_id=body.campaign_id,
        created_by_user_id=user.id,
        name=body.name,
        fields=[f.model_dump() for f in body.fields],
    )
    check_create(template, ctx)
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return project(template, ctx)


@router.patch("/templates/{template_id}", response_model=None,
              responses={200: {"model": TemplateGMResponse, "description": _GM_OR_PARTY}})
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    ctx: CampaignContext = Depends(_template_ctx),
    db: AsyncSession = Depends(get_db),
):
    template = await scoped_get(db, CharacterSheetTemplate, ctx, template_id)
    if body.name is not None:
        template.name = body.name
    if body.fields is not None:
        template.fields = [f.model_dump() for f in body.fields]
    await db.commit()
    await db.refresh(template)
    return await _project_template(db, template, ctx)


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    ctx: CampaignContext = Depends(_template_ctx),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Deleting a template cascades to every character sheet built from it
    (see character_sheets.template_id's ondelete="CASCADE") — the frontend is
    expected to warn using the list response's character_count before calling
    this, same pattern as removing a campaign member with delete_entries."""
    template = await scoped_get(db, CharacterSheetTemplate, ctx, template_id)
    # The cascade must not destroy sheets the caller cannot see: refuse (as a
    # missing template) when any of its sheets is hidden from ctx.
    total = (await db.execute(
        select(func.count(CharacterSheet.id)).where(CharacterSheet.template_id == template.id)
    )).scalar_one()
    if total != (await _visible_sheet_counts(db, ctx, [template.id])).get(template.id, 0):
        not_found()
    await db.delete(template)
    await db.commit()


# ── Character sheets ─────────────────────────────────────────────────────────

@router.get("/", response_model=None,
            responses={200: {"model": list[CharacterSheetGMResponse], "description": _GM_OR_PARTY}})
async def list_character_sheets(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(scoped_select(CharacterSheet, ctx).order_by(CharacterSheet.name))
    return await project_all(db, result.scalars().all(), ctx)


@router.post("/", response_model=None, status_code=201,
             responses={201: {"model": CharacterSheetGMResponse, "description": _GM_OR_PARTY}})
async def create_character_sheet(
    request: Request,
    body: CharacterSheetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id)
    # A template of another Campaign is missing (scoped to ctx's Campaign).
    await scoped_get(db, CharacterSheetTemplate, ctx, body.template_id)
    sheet = CharacterSheet(
        campaign_id=body.campaign_id,
        template_id=body.template_id,
        created_by_user_id=user.id,
        name=body.name,
        data=body.data,
    )
    check_create(sheet, ctx)
    db.add(sheet)
    await db.commit()
    await db.refresh(sheet)
    return project(sheet, ctx)


@router.get("/{sheet_id}", response_model=None,
            responses={200: {"model": CharacterSheetGMResponse, "description": _GM_OR_PARTY}})
async def get_character_sheet(
    sheet_id: uuid.UUID,
    ctx: CampaignContext = Depends(_sheet_ctx),
    db: AsyncSession = Depends(get_db),
):
    return project(await scoped_get(db, CharacterSheet, ctx, sheet_id), ctx)


@router.patch("/{sheet_id}", response_model=None,
              responses={200: {"model": CharacterSheetGMResponse, "description": _GM_OR_PARTY}})
async def update_character_sheet(
    sheet_id: uuid.UUID,
    body: CharacterSheetUpdate,
    ctx: CampaignContext = Depends(_sheet_ctx),
    db: AsyncSession = Depends(get_db),
):
    sheet = await scoped_get(db, CharacterSheet, ctx, sheet_id)
    if body.name is not None:
        sheet.name = body.name
    if body.data is not None:
        # Full replace, not a merge — the frontend always sends the complete
        # field-value map back (it has the template's full field list to
        # build it from), same convention as e.g. SessionPlan updates.
        sheet.data = body.data
    await db.commit()
    await db.refresh(sheet)
    return project(sheet, ctx)


@router.delete("/{sheet_id}", status_code=204)
async def delete_character_sheet(
    sheet_id: uuid.UUID,
    ctx: CampaignContext = Depends(_sheet_ctx),
    db: AsyncSession = Depends(get_db),
) -> None:
    sheet = await scoped_get(db, CharacterSheet, ctx, sheet_id)
    await db.delete(sheet)
    await db.commit()
