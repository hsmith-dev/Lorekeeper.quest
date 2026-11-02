"""Jobs, mounted under /api/jobs (E0-Jobs.7, AD-5, AD-13).

    GET  /stream?campaign_id=   SSE: `subscribed`, then the `job` events the caller may see
    GET  /?campaign_id=&status= the caller's visible Jobs (running, queued, finished <= 24 h), newest first
    GET  /{job_id}              one Job (JobResponse)
    POST /{job_id}/retry        a failed Job, queued again: 202 {"job_id"}
    POST /{job_id}/cancel       a queued Job, cancelled: 200 JobResponse

Who sees what is app/access/jobs.py: a GM every Job of the Campaign, a
Player the Jobs they started, the member view (preview) none; `result_ref`
reaches a non-GM only as `{"kind", "id"}` of a result they can see now.
Hidden, missing, another Campaign's and malformed ids are the one
`404 {"detail":"Not found"}`. Retry and cancel need a writable ctx (a
preview write is 404); a Job in the wrong state is
`409 {"detail": "Only queued Jobs can be cancelled"}` (or the retry
equivalent). State changes live in app/jobs/control.py.

The stream (bearer header) frames:

    event: subscribed       data: {}                        first, once the subscription is live
    event: job              data: {job_id, kind, status, progress, stage, eta_seconds,
                                   error_code, error_message, result_ref}
    event: ping             data: {}                        every 15 s
    event: access_changed   data: {"detail": "Not found"}   then the stream ends

On every `subscribed` the client refetches its Jobs (no event ids, no
replay). The stream stands on the caller's real grant; under
`X-Lorekeeper-Preview: member` it is filtered as the member view. nginx: the
exact `/api/jobs/stream` location (generic zone, buffering off, 1 h read
timeout). Every route is limited per user (`user_or_ip`).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import (
    CampaignContext, get_job, job_event_stream, job_response, list_jobs, queue_positions, require_campaign,
    require_campaign_for, stream_ctx,
)
from app.core.limiter import limiter, user_or_ip
from app.core.sse import sse_response
from app.db.models.job import Job
from app.db.session import get_db
from app.domain.enums import JobStatus
from app.jobs.control import JobConflict, cancel_job, retry_job
from app.jobs.enqueue import job_accepted
from app.schemas.jobs import JobListResponse, JobResponse

router = APIRouter()

READ_RATE = "120/minute"
WRITE_RATE = "30/minute"
STREAM_RATE = "30/minute"


@router.get("/stream", response_model=None, responses={
    200: {"content": {"text/event-stream": {}}, "description": "The Campaign's Job events (SSE)"},
})
@limiter.limit(STREAM_RATE, key_func=user_or_ip)
async def job_stream(
    request: Request,
    ctx: CampaignContext = Depends(require_campaign("player", preview=False)),
    db: AsyncSession = Depends(get_db),
):
    filter_ctx = stream_ctx(request, ctx)
    bind = db.bind
    # The request session would otherwise be held (idle) for the whole stream.
    await db.close()
    return sse_response(job_event_stream(filter_ctx, bind=bind), ctx=ctx, bind=bind)


@router.get("/", response_model=JobListResponse)
@limiter.limit(READ_RATE, key_func=user_or_ip)
async def list_campaign_jobs(
    request: Request,
    status: JobStatus | None = None,
    ctx: CampaignContext = Depends(require_campaign("player")),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    jobs = await list_jobs(db, ctx, status=status)
    positions = await queue_positions(db, ctx) if any(j.status == JobStatus.QUEUED for j in jobs) else {}
    return JobListResponse(jobs=[await job_response(db, ctx, job, positions=positions) for job in jobs])


@router.get("/{job_id}", response_model=JobResponse)
@limiter.limit(READ_RATE, key_func=user_or_ip)
async def get_campaign_job(
    request: Request,
    job_id: str,
    ctx: CampaignContext = Depends(require_campaign_for(Job, "job_id", "player")),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    return await job_response(db, ctx, await get_job(db, ctx, job_id))


@router.post("/{job_id}/retry", status_code=202, response_model=None, responses={
    202: {"description": "Queued again", "content": {"application/json": {"example": {"job_id": "…"}}}},
    409: {"description": "Not a failed Job"},
})
@limiter.limit(WRITE_RATE, key_func=user_or_ip)
async def retry_campaign_job(
    request: Request,
    job_id: str,
    ctx: CampaignContext = Depends(require_campaign_for(Job, "job_id", "player")),
    db: AsyncSession = Depends(get_db),
):
    try:
        new_id = await retry_job(db, ctx, job_id)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from None
    return job_accepted(new_id)


@router.post("/{job_id}/cancel", response_model=JobResponse, responses={409: {"description": "Not a queued Job"}})
@limiter.limit(WRITE_RATE, key_func=user_or_ip)
async def cancel_campaign_job(
    request: Request,
    job_id: str,
    ctx: CampaignContext = Depends(require_campaign_for(Job, "job_id", "player")),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    try:
        job = await cancel_job(db, ctx, job_id)
    except JobConflict as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from None
    return await job_response(db, ctx, job)
