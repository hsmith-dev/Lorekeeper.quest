"""`enqueue`: the only way to create a Job (AD-2, E0-Jobs.2).

    job_id = await enqueue(db, ctx, "extraction.run", {"journal_id": str(entry.id)},
                           idempotency_key=f"extraction.run:{entry.id}:{entry_hash}")
    await db.commit()
    return job_accepted(job_id)          # 202 {"job_id": "..."}

The Job is written in the caller's transaction and handed to RQ only after
that transaction commits (app/jobs/outbox.py): a rollback leaves no row and
pushes nothing. The queue comes from the kind's registration.

Every ValueError (bad kind, payload, key, ctx or dependency) is raised before
anything is written.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import sqlalchemy as sa
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.context import CampaignContext
from app.db.models.job import ACTIVE_STATUSES, Job
from app.domain.enums import JobStatus
from app.jobs import outbox
from app.jobs.registry import get_kind

# Words that mark a payload key as a secret (raw API keys are never queued,
# AD-3). Matched per word, so `max_tokens` (word "tokens") is allowed.
_SECRET_WORDS = frozenset({"token", "password", "passwd", "secret", "apikey"})
_CAMEL_1 = re.compile(r"([A-Z]+)([A-Z][a-z])")   # "APIKey"      -> "API_Key"
_CAMEL_2 = re.compile(r"([a-z0-9])([A-Z])")      # "accessToken" -> "access_Token"
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")
# Concurrent inserts of one key: the loser re-selects; a winner that finished
# in between frees the key, so try again a few times.
_INSERT_ATTEMPTS = 3


def _key_words(key: str) -> list[str]:
    spaced = _CAMEL_2.sub(r"\1_\2", _CAMEL_1.sub(r"\1_\2", key))
    return [w for w in _WORD_SPLIT.split(spaced.lower()) if w]


def is_secret_key(key: str) -> bool:
    """True for a key named like a secret: a word token / password / passwd /
    secret, or api_key / apikey (any case, snake, kebab or camelCase)."""
    words = _key_words(key)
    if any(w in _SECRET_WORDS for w in words):
        return True
    return any(a == "api" and b == "key" for a, b in zip(words, words[1:]))


def _check_payload(value: Any, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"enqueue: {path} has a non-string key {key!r}")
            if is_secret_key(key):
                raise ValueError(f"enqueue: {path} has a secret-like key {key!r}; never queue credentials")
            _check_payload(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check_payload(item, f"{path}[{i}]")


def _validate_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("enqueue: payload must be a dict")
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"enqueue: payload is not JSON-serialisable ({exc})") from None
    _check_payload(payload)


def _parse_job_id(value: Any) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("enqueue: unknown dependency") from None


async def _active_with_key(db: AsyncSession, key: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    row = (await db.execute(
        sa.select(Job.id, Job.campaign_id).where(
            Job.idempotency_key == key, Job.status.in_([s.value for s in ACTIVE_STATUSES]))
    )).first()
    return (row.id, row.campaign_id) if row is not None else None


def _existing_or_raise(found: tuple[uuid.UUID, uuid.UUID], ctx: CampaignContext) -> uuid.UUID:
    job_id, campaign_id = found
    if campaign_id != ctx.campaign_id:
        # The active-key index is global: never return or reveal another
        # Campaign's Job. Content-derived keys include ids, so this is a bug
        # in the caller's key, not a race to recover from.
        raise ValueError("enqueue: idempotency_key is in use by an active Job in another Campaign")
    return job_id


async def enqueue(
    db: AsyncSession,
    ctx: CampaignContext,
    kind: str,
    payload: dict[str, Any],
    *,
    idempotency_key: str | None = None,
    depends_on_job_id: uuid.UUID | str | None = None,
) -> uuid.UUID:
    """Create a `queued` Job of `kind` in ctx's Campaign and return its id.

    The Job is pushed (or, under JOBS_EAGER, run) only when `db` commits. An
    active (queued/running) Job with the same `idempotency_key` in this
    Campaign is returned instead, writing nothing. With `depends_on_job_id`,
    the Job waits `queued` until that Job (same Campaign) reaches any terminal
    status, then always runs (`job.dependency_status` tells the handler how
    it ended)."""
    job_kind = get_kind(kind)
    _validate_payload(payload)
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ValueError("enqueue: idempotency_key is required")
    if ctx.read_only or ctx.user_id is None:
        raise ValueError("enqueue: needs a user's writable ctx (not a reduced or anonymous one)")

    hold = False
    dep_id: uuid.UUID | None = None
    if depends_on_job_id is not None:
        dep_id = _parse_job_id(depends_on_job_id)
        # FOR SHARE: a worker finishing the dependency waits for this
        # transaction, so its after-commit release sees the dependent.
        dep = (await db.execute(
            sa.select(Job.campaign_id, Job.status).where(Job.id == dep_id).with_for_update(read=True)
        )).first()
        if dep is None or dep.campaign_id != ctx.campaign_id:
            raise ValueError("enqueue: unknown dependency")
        hold = dep.status in ACTIVE_STATUSES

    for _ in range(_INSERT_ATTEMPTS):
        found = await _active_with_key(db, idempotency_key)
        if found is not None:
            return _existing_or_raise(found, ctx)
        job = Job(
            id=uuid.uuid4(), campaign_id=ctx.campaign_id, kind=job_kind.name, queue=job_kind.queue,
            status=JobStatus.QUEUED, payload=payload, idempotency_key=idempotency_key,
            ctx_kind=ctx.role, ctx_user_id=ctx.user_id, created_by=ctx.user_id,
            ctx_audience=ctx.audience.level.value, access_epoch=ctx.access_epoch,
            depends_on_job_id=dep_id,
        )
        # The caller's own pending changes go out first, outside the
        # savepoint, so a lost race rolls back only this Job's insert.
        await db.flush()
        try:
            async with db.begin_nested():
                db.add(job)
                await db.flush()
        except IntegrityError as exc:
            if "uq_jobs_idempotency_key_active" not in str(exc.orig):
                raise
            continue  # a concurrent enqueue won: re-select
        if not hold:
            outbox.record_pending(db.sync_session, job.id, job_kind.queue, job_kind.name)
        return job.id
    raise RuntimeError("enqueue: could not insert or find the Job for this idempotency_key")


def job_accepted(job_id: uuid.UUID) -> JSONResponse:
    """The route response for a started Job: `202 {"job_id": "..."}`."""
    return JSONResponse(status_code=202, content={"job_id": str(job_id)})


__all__ = ["enqueue", "is_secret_key", "job_accepted"]
