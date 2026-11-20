import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func

from app.access import (
    CampaignContext, can_write, check_create, ctx_for_request, project, require_campaign, require_campaign_for,
    scoped_get,
    scoped_select,
)
from app.clients.errors import ModelServiceError
from app.core.limiter import limiter
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.source import SourceDocument, SourceChunk
from app.schemas.source import SourceDocumentResponse
from app.api.deps import PARTY_READ, get_current_user
from app.services.source_service import extract_text, chunk_text
from app.services.embedding_service import embed_many

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_TYPES = {"text/plain", "text/markdown", "application/pdf"}
_MAX_BYTES = 15 * 1024 * 1024  # 15 MB

# Source documents are GM material (E0-Access.5): GMs of the Campaign (Owner
# or Co-GM) upload and delete them; a Player lists only documents whose
# Visibility covers them. Every denial, and a hidden document, is the one 404.
# Every write calls can_write on the row (E0-Access.6). Account gate
# (app/api/deps.py): the list is a Party read (openapi_extra=PARTY_READ);
# upload and delete need a paid or granted account.
_source_gm = require_campaign_for(SourceDocument, "source_id", "gm")


@router.get("/", response_model=list[SourceDocumentResponse], openapi_extra=PARTY_READ)
async def list_sources(
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        scoped_select(SourceDocument, ctx)
        .outerjoin(SourceChunk, SourceChunk.source_document_id == SourceDocument.id)
        .add_columns(func.count(SourceChunk.id))
        .group_by(SourceDocument.id)
        .order_by(SourceDocument.created_at.desc(), SourceDocument.id)
    )
    return [project(doc, ctx, extra={"chunk_count": count}) for doc, count in result.all()]


@router.post("/", response_model=SourceDocumentResponse, status_code=201)
@limiter.limit("10/minute")
async def upload_source(
    request: Request,
    campaign_id: uuid.UUID = Form(...),
    title: str | None = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await ctx_for_request(request, db, user, campaign_id, "gm")

    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_TYPES and not file.filename.lower().endswith((".txt", ".md", ".pdf")):
        raise HTTPException(status_code=415, detail="Upload a .txt, .md, or .pdf file.")

    contents = await file.read()
    if len(contents) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 15 MB limit.")

    text = extract_text(file.filename, content_type, contents)
    if not text:
        raise HTTPException(status_code=422, detail="Could not extract any text from this file.")

    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=422, detail="File produced no usable content chunks.")

    doc = SourceDocument(
        user_id=user.id,
        campaign_id=campaign_id,
        title=(title or file.filename).strip()[:200],
        filename=file.filename,
    )
    check_create(doc, ctx)

    # Every chunk's vector before anything is written: with the ml sidecar
    # down the upload is a 503 and nothing is committed.
    try:
        vectors = await embed_many(chunks)
    except ModelServiceError as exc:
        logger.warning("Source upload failed, ml sidecar: %s", exc)
        raise HTTPException(status_code=503, detail="Embedding model unavailable")

    db.add(doc)
    await db.flush()

    for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
        db.add(SourceChunk(
            source_document_id=doc.id,
            user_id=user.id,
            campaign_id=campaign_id,
            chunk_index=i,
            content=chunk,
            embedding=vector,
        ))

    await db.commit()
    await db.refresh(doc)
    return project(doc, ctx, extra={"chunk_count": len(chunks)})


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    ctx: CampaignContext = Depends(_source_gm),
    db: AsyncSession = Depends(get_db),
) -> None:
    doc = await scoped_get(db, SourceDocument, ctx, source_id)
    can_write(ctx, doc)
    await db.delete(doc)
    await db.commit()
