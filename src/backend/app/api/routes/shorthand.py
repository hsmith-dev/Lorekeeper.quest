import uuid
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    CampaignContext, check_create, ctx_for_request, project, project_all, require_campaign, require_campaign_for,
    scoped_get, scoped_select,
)
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.shorthand import ShorthandTerm
from app.schemas.shorthand import ShorthandCreate, ShorthandUpdate, ShorthandResponse
from app.api.deps import get_current_user

router = APIRouter()

# Shorthand terms are GM vocabulary (E0-Access.5): any GM of the term's
# Campaign (Owner or Co-GM) may create, edit or delete them; a Player reads
# only the terms whose Visibility covers them. Every denial, and a hidden
# term, is the one 404.
_term_gm = require_campaign_for(ShorthandTerm, "term_id", "gm")


@router.get("/", response_model=list[ShorthandResponse])
async def list_shorthand(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(scoped_select(ShorthandTerm, ctx).order_by(ShorthandTerm.term, ShorthandTerm.id))
    return await project_all(db, result.scalars().all(), ctx)


@router.post("/", response_model=ShorthandResponse, status_code=201)
async def create_shorthand(
    request: Request,
    body: ShorthandCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, body.campaign_id, "gm")
    term = ShorthandTerm(
        user_id=user.id, campaign_id=body.campaign_id,
        term=body.term.strip(), meaning=body.meaning.strip(), usage=(body.usage or "").strip() or None,
    )
    check_create(term, ctx)
    db.add(term)
    await db.commit()
    await db.refresh(term)
    return project(term, ctx)


@router.put("/{term_id}", response_model=ShorthandResponse)
async def update_shorthand(
    term_id: uuid.UUID,
    body: ShorthandUpdate,
    ctx: CampaignContext = Depends(_term_gm),
    db: AsyncSession = Depends(get_db),
):
    term = await scoped_get(db, ShorthandTerm, ctx, term_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(term, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(term)
    return project(term, ctx)


@router.delete("/{term_id}", status_code=204)
async def delete_shorthand(
    term_id: uuid.UUID,
    ctx: CampaignContext = Depends(_term_gm),
    db: AsyncSession = Depends(get_db),
) -> None:
    term = await scoped_get(db, ShorthandTerm, ctx, term_id)
    await db.delete(term)
    await db.commit()
