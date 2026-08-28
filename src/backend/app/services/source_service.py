import io
import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.source import SourceChunk, SourceDocument
from app.services.embedding_service import embed

_CHUNK_WORDS = 350
_CHUNK_OVERLAP_WORDS = 50


def extract_text(filename: str, content_type: str | None, contents: bytes) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".pdf") or (content_type and "pdf" in content_type):
        import pypdf
        reader = pypdf.PdfReader(io.BytesIO(contents))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
    try:
        return contents.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Unsupported file encoding. Upload a UTF-8 text, Markdown, or PDF file.")


def chunk_text(text: str, chunk_words: int = _CHUNK_WORDS, overlap_words: int = _CHUNK_OVERLAP_WORDS) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    step = chunk_words - overlap_words
    while start < len(words):
        chunk = " ".join(words[start:start + chunk_words])
        if chunk.strip():
            chunks.append(chunk.strip())
        start += step
    return chunks


async def retrieve_canon_context(
    db: AsyncSession,
    query_text: str,
    user_id: uuid.UUID,
    campaign_id: uuid.UUID | None,
    limit: int = 3,
    max_distance: float = 0.75,
) -> tuple[str | None, list[str]]:
    """Return (canon_context_text, source_titles) for the top-k most relevant
    source chunks. Chunks are relevance-gated by cosine distance (0 =
    identical, 2 = opposite), not just top-k — without the cutoff, every
    query got the 3 nearest chunks regardless of whether they had anything to
    do with the question, polluting the prompt with (and crediting sources
    for) unrelated canon."""
    try:
        query_embedding = embed(query_text)
    except Exception:
        return None, []

    # Campaign context is shared: ground on every source doc uploaded to that
    # campaign, not just ones this particular user uploaded. Access to
    # campaign_id is verified by the caller before this runs. With no campaign
    # selected, fall back to scoping by the requesting user alone.
    base_filter = SourceChunk.campaign_id == campaign_id if campaign_id else SourceChunk.user_id == user_id

    distance = SourceChunk.embedding.cosine_distance(query_embedding)
    result = await db.execute(
        select(SourceChunk, SourceDocument.title, distance.label("dist"))
        .join(SourceDocument, SourceChunk.source_document_id == SourceDocument.id)
        .where(base_filter, SourceChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
    )
    rows = result.all()
    if not rows:
        return None, []

    titles = []
    blocks = []
    for chunk, title, dist in rows:
        if dist is not None and dist > max_distance:
            continue
        blocks.append(f"[{title}]\n{chunk.content}")
        if title not in titles:
            titles.append(title)

    if not blocks:
        return None, []
    return "\n\n".join(blocks), titles
