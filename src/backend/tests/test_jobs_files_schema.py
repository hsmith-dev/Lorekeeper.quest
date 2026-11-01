"""E0-Jobs.1: the F2-jobs-files constraints on the migrated schema, and the
Job error-code sets in app/jobs/errors.py.

Visibility of jobs and stored_files is CI-11's (tests/access/test_registry_property.py)
and tests/access/test_audience.py's; the CHECK-vs-StrEnum sync is CI-10's.
This module checks what the database itself enforces.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.core import errors as llm_errors
from app.db.models import Campaign, DataBackfill, Genre, Job, StoredFile, User
from app.domain import enums as domain_enums
from app.domain.enums import JobErrorCode, JobQueue, JobStatus
from app.jobs import RETRYABLE_CODES, TERMINAL_CODES
from app.jobs import errors as job_errors


def _user(label: str) -> User:
    return User(email=f"jobs-{label}-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                display_name=label, access_granted=True, access_source="promo")


@pytest_asyncio.fixture
async def campaign(db) -> Campaign:
    owner = _user("owner")
    db.add(owner)
    await db.flush()
    c = Campaign(user_id=owner.id, name="Jobs", genre=Genre.fantasy)
    db.add(c)
    await db.flush()
    return c


def _job(c: Campaign, key: str, status: str = JobStatus.QUEUED, **kw) -> Job:
    values = dict(campaign_id=c.id, kind="system.noop", queue=JobQueue.INTERACTIVE, status=status,
                  idempotency_key=key, ctx_kind="user", created_by=c.user_id)
    values.update(kw)
    return Job(**values)


def _file(c: Campaign, cache_key: str | None, *, kind: str = "chronicle_pdf", stale: bool = False,
          **kw) -> StoredFile:
    return StoredFile(campaign_id=c.id, kind=kind, storage_key=uuid.uuid4().hex, content_type="application/pdf",
                      size=1, sha256="0" * 64, cache_key=cache_key, stale=stale, **kw)


async def _accepted(db, *rows) -> None:
    db.add_all(rows)
    await db.flush()


async def _rejected(db, row, constraint: str) -> None:
    with pytest.raises(IntegrityError) as exc:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    assert constraint in str(exc.value), str(exc.value)


# ── Idempotency (partial unique index) ─────────────────────────────────────

@pytest.mark.parametrize("first, second", [
    (JobStatus.QUEUED, JobStatus.QUEUED),
    (JobStatus.QUEUED, JobStatus.RUNNING),
    (JobStatus.RUNNING, JobStatus.QUEUED),
])
async def test_idempotency_key_unique_among_active_jobs(db, campaign, first, second):
    await _accepted(db, _job(campaign, "extraction.run:1:h", first))
    await _rejected(db, _job(campaign, "extraction.run:1:h", second), "uq_jobs_idempotency_key_active")


@pytest.mark.parametrize("finished", [JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED])
async def test_idempotency_key_reusable_after_a_terminal_status(db, campaign, finished):
    await _accepted(db, _job(campaign, "extraction.run:2:h", finished))
    await _accepted(db, _job(campaign, "extraction.run:2:h", JobStatus.QUEUED))
    await _accepted(db, _job(campaign, "extraction.run:2:h", finished))
    count = await db.scalar(sa.select(sa.func.count()).select_from(Job).where(
        Job.idempotency_key == "extraction.run:2:h"))
    assert count == 3


async def test_finishing_the_active_job_frees_its_key(db, campaign):
    first = _job(campaign, "k:free")
    await _accepted(db, first)
    first.status = JobStatus.DONE
    await db.flush()
    await _accepted(db, _job(campaign, "k:free"))


# ── Cache key (partial unique index) ───────────────────────────────────────

async def test_cache_key_unique_among_fresh_files(db, campaign):
    await _accepted(db, _file(campaign, "ck1"))
    await _rejected(db, _file(campaign, "ck1"), "uq_stored_files_cache_key_fresh")


async def test_cache_key_reusable_once_stale(db, campaign):
    await _accepted(db, _file(campaign, "ck2", stale=True), _file(campaign, "ck2"))
    await _accepted(db, _file(campaign, "ck2", stale=True))


async def test_cache_key_is_per_campaign_and_kind(db, campaign):
    other_owner = _user("other")
    db.add(other_owner)
    await db.flush()
    other = Campaign(user_id=other_owner.id, name="Other", genre=Genre.fantasy)
    db.add(other)
    await db.flush()
    await _accepted(db, _file(campaign, "ck3"), _file(campaign, "ck3", kind="narration_audio"),
                    _file(other, "ck3"), _file(campaign, None), _file(campaign, None))


# ── CHECKs from the StrEnums ───────────────────────────────────────────────

@pytest.mark.parametrize("field, value, constraint", [
    ("status", "paused", "ck_jobs_status"),
    ("queue", "x", "ck_jobs_queue"),
    ("error_code", "nope", "ck_jobs_error_code"),
])
async def test_job_checks_reject_unknown_values(db, campaign, field, value, constraint):
    await _rejected(db, _job(campaign, f"k:{field}", **{field: value}), constraint)


async def test_job_checks_accept_every_member(db, campaign):
    rows = [_job(campaign, f"s:{s}", s) for s in JobStatus]
    rows += [_job(campaign, f"q:{q}", JobStatus.DONE, queue=q) for q in JobQueue]
    rows += [_job(campaign, f"e:{e}", JobStatus.FAILED, error_code=e) for e in JobErrorCode]
    rows.append(_job(campaign, "e:none", JobStatus.DONE, error_code=None))
    await _accepted(db, *rows)


async def test_data_backfills_status_check(db):
    await _accepted(db, DataBackfill(name=f"bf_{uuid.uuid4().hex[:8]}", status=JobStatus.RUNNING))
    await _rejected(db, DataBackfill(name=f"bf_{uuid.uuid4().hex[:8]}", status="paused"),
                    "ck_data_backfills_status")
    name = f"bf_{uuid.uuid4().hex[:8]}"
    first = DataBackfill(name=name)
    await _accepted(db, first)
    db.expunge(first)  # else the ORM refuses the duplicate identity before Postgres sees it
    await _rejected(db, DataBackfill(name=name), "data_backfills_pkey")


# ── Server defaults and ON DELETE ──────────────────────────────────────────

async def test_job_server_defaults(db, campaign):
    row = (await db.execute(sa.text(
        "INSERT INTO jobs (id, campaign_id, kind, queue, idempotency_key, ctx_kind) "
        "VALUES (:id, :cid, 'system.noop', 'interactive', :key, 'user') "
        "RETURNING status, priority, payload = '{}'::jsonb, access_epoch, attempts, max_attempts, created_at IS NOT NULL"
    ), {"id": uuid.uuid4(), "cid": campaign.id, "key": uuid.uuid4().hex})).one()
    assert tuple(row) == ("queued", 0, True, 0, 0, 3, True)


async def test_file_owner_delete_removes_the_file(db, campaign):
    player = _user("player")
    db.add(player)
    await db.flush()
    f = _file(campaign, None, audience_owner_id=player.id, created_by=player.id)
    await _accepted(db, f)
    file_id = f.id
    await db.execute(sa.delete(User).where(User.id == player.id))
    assert await db.scalar(sa.select(sa.func.count()).select_from(StoredFile).where(StoredFile.id == file_id)) == 0


# ── app/jobs/errors.py ─────────────────────────────────────────────────────

def test_job_error_code_is_the_domain_enum():
    assert job_errors.JobErrorCode is domain_enums.JobErrorCode


def test_terminal_and_retryable_codes_partition_the_enum():
    assert TERMINAL_CODES == {JobErrorCode.LLM_CONFIG, JobErrorCode.AI_OUTPUT_UNUSABLE,
                              JobErrorCode.PROMPT_TOO_LARGE, JobErrorCode.PERMISSION_CHANGED}
    assert not TERMINAL_CODES & RETRYABLE_CODES
    assert TERMINAL_CODES | RETRYABLE_CODES == set(JobErrorCode)


def test_llm_error_codes_are_members_and_classified_like_e0_llm():
    values = {c.value for c in JobErrorCode}
    for cls in (*llm_errors.RETRYABLE, *llm_errors.TERMINAL):
        assert cls.code in values, cls.__name__
    assert {JobErrorCode(c.code) for c in llm_errors.TERMINAL} <= TERMINAL_CODES
    assert {JobErrorCode(c.code) for c in llm_errors.RETRYABLE} <= RETRYABLE_CODES
