import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.limiter import limiter
from app.db.session import get_db
from app.db.models.user import User
from app.db.models.source import SourceDocument, SourceChunk
from app.schemas.source import SourceDocumentResponse
from app.api.deps import get_current_user, get_campaign_with_access, accessible_campaign_ids
from app.services.source_service import extract_text, chunk_text
from app.services.embedding_service import embed

router = APIRouter()

_ALLOWED_TYPES = {"text/plain", "text/markdown", "application/pdf"}
_MAX_BYTES = 15 * 1024 * 1024  # 15 MB


@router.get("/", response_model=list[SourceDocumentResponse])
async def list_sources(
    campaign_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SourceDocumentResponse]:
    await get_campaign_with_access(db, campaign_id, user)
    result = await db.execute(
        select(SourceDocument, func.count(SourceChunk.id))
        .outerjoin(SourceChunk, SourceChunk.source_document_id == SourceDocument.id)
        .where(SourceDocument.campaign_id == campaign_id)
        .group_by(SourceDocument.id)
        .order_by(SourceDocument.created_at.desc())
    )
    return [
        SourceDocumentResponse(
            id=doc.id,
            campaign_id=doc.campaign_id,
            title=doc.title,
            filename=doc.filename,
            chunk_count=count,
            created_at=doc.created_at,
        )
        for doc, count in result.all()
    ]


@router.post("/", response_model=SourceDocumentResponse, status_code=201)
@limiter.limit("10/minute")
async def upload_source(
    request: Request,
    campaign_id: uuid.UUID = Form(...),
    title: str | None = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceDocumentResponse:
    await get_campaign_with_access(db, campaign_id, user)

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
    db.add(doc)
    await db.flush()

    for i, chunk in enumerate(chunks):
        db.add(SourceChunk(
            source_document_id=doc.id,
            user_id=user.id,
            campaign_id=campaign_id,
            chunk_index=i,
            content=chunk,
            embedding=embed(chunk),
        ))

    await db.commit()
    await db.refresh(doc)

    return SourceDocumentResponse(
        id=doc.id,
        campaign_id=doc.campaign_id,
        title=doc.title,
        filename=doc.filename,
        chunk_count=len(chunks),
        created_at=doc.created_at,
    )


@router.delete("/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(SourceDocument).where(SourceDocument.id == source_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Source document not found")
    await get_campaign_with_access(db, doc.campaign_id, user)
    await db.delete(doc)
    await db.commit()
