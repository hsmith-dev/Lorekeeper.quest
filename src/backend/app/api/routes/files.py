"""Stored files, mounted under /api/files (E0-Jobs.8, AD-14, AR-14).

`GET /{file_id}` answers an empty body with `X-Accel-Redirect:
/_files/<storage_key>`; nginx serves the bytes from its `internal`
`/_files/` location (nginx/locations.conf), so the volume is never reachable
by URL. The file must pass both access checks (app/access/files.py: SQL
`scoped_get` and Python `audience_of` over all of its sources) and its bytes
must be on the volume. Missing, hidden, another Campaign's, a malformed id,
stale for a non-GM (preview included) and bytes missing are all the one
`404 {"detail":"Not found"}`. A matching If-None-Match is 304.

Tree files (map tiles) are served by their owning route (E10) with
`file_service.open` and `file_service.accel_response(file, subpath)`.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import CampaignContext, require_campaign_for
from app.db.models.stored_file import StoredFile
from app.db.session import get_db
from app.services import file_service

router = APIRouter()


@router.get("/{file_id}", response_class=Response)
async def get_file(
    request: Request,
    file_id: str,
    ctx: CampaignContext = Depends(require_campaign_for(StoredFile, "file_id", "player")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await file_service.open(db, ctx, file_id)
    return file_service.accel_response(row, access_epoch=ctx.access_epoch, request=request)
