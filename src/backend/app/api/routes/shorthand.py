import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models.user import User
from app.db.models.shorthand import ShorthandTerm
from app.schemas.shorthand import ShorthandCreate, ShorthandUpdate, ShorthandResponse
from app.api.deps import get_current_user, get_campaign_with_access

router = APIRouter()


async def _get_accessible_term(db: AsyncSession, term_id: uuid.UUID, user: User) -> ShorthandTerm:
    """Same access model as NPCs — shorthand definitions are shared campaign
    knowledge, so any member (not just the term's creator) may read/edit/
    delete them."""
    term = await db.get(ShorthandTerm, term_id)
    if not term:
        raise HTTPException(status_code=404, detail="Shorthand term not found")
    await get_campaign_with_access(db, term.campaign_id, user)
    return term


@router.get("/", response_model=list[ShorthandResponse])
async def list_shorthand(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ShorthandResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(ShorthandTerm).where(ShorthandTerm.campaign_id == campaign_id).order_by(ShorthandTerm.term)
    )
    return list(result.scalars().all())


@router.post("/", response_model=ShorthandResponse, status_code=201)
async def create_shorthand(
    body: ShorthandCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShorthandResponse:
    await get_campaign_with_access(db, body.campaign_id, user)
    term = ShorthandTerm(
        user_id=user.id, campaign_id=body.campaign_id,
        term=body.term.strip(), meaning=body.meaning.strip(), usage=(body.usage or "").strip() or None,
    )
    db.add(term)
    await db.commit()
    await db.refresh(term)
    return term


@router.put("/{term_id}", response_model=ShorthandResponse)
async def update_shorthand(
    term_id: uuid.UUID,
    body: ShorthandUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ShorthandResponse:
    term = await _get_accessible_term(db, term_id, user)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(term, field, value.strip() if isinstance(value, str) else value)
    await db.commit()
    await db.refresh(term)
    return term


@router.delete("/{term_id}", status_code=204)
async def delete_shorthand(
    term_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    term = await _get_accessible_term(db, term_id, user)
    await db.delete(term)
    await db.commit()
