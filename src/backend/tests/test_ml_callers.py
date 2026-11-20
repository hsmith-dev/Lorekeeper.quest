"""E0-Platform.6: the backend's ml callers with the sidecar up and down.

Journal save degrades (201, no tags, NULL vectors, a WARNING); source
upload, journal reindex and NPC extract are a 503 with nothing committed;
GET /api/admin/sidecars reports both sidecars and never 5xx; the app
boots without loading or importing any model package.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.api.routes import admin as admin_routes
from app.clients.errors import ModelServiceUnavailable
from app.db.models.campaign import Campaign, Genre
from app.db.models.journal import JournalEntry
from app.clients.fakes import fake_vector
from app.db.models.source import SourceChunk, SourceDocument
from app.services import dedup_service, embedding_service, nlp_service
from tests.ev4.fixtures import bearer, create_user

BACKEND = Path(__file__).resolve().parents[1]


class _DownML:
    """Every ml call fails as an unreachable sidecar does."""

    async def embed(self, texts):
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")

    async def ner(self, text):
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")

    async def status(self):
        raise ModelServiceUnavailable("ml sidecar unreachable at http://ml.test:8001")


class _DownSTT:
    async def status(self):
        raise ModelServiceUnavailable("stt sidecar unreachable at http://stt.test:8002")


class _FakeValkey:
    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return int(key in self.keys)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.keys[key] = value


@pytest.fixture(autouse=True)
def fake_valkey(monkeypatch):
    store = _FakeValkey()
    monkeypatch.setattr(dedup_service, "get_valkey", lambda: store)
    return store


@pytest.fixture
def ml_down(monkeypatch):
    down = _DownML()
    monkeypatch.setattr(embedding_service, "_override", down)
    monkeypatch.setattr(nlp_service, "get_ml_client", lambda: down)
    return down


@pytest_asyncio.fixture
async def gm(db):
    owner = await create_user(db, "mlc_owner")
    cid = uuid.uuid4()
    db.add(Campaign(id=cid, user_id=owner.id, name="ML", genre=Genre.fantasy))
    await db.commit()
    return owner, cid


# ── Journal save ───────────────────────────────────────────────────────────

async def _save(client, owner, cid, narrative):
    return await client.post("/api/journals/generate", headers=bearer(owner), json={
        "notes": "Borin met Mira", "campaign_id": str(cid), "entry_hash": uuid.uuid4().hex,
        "narrative": narrative})


async def test_journal_save_with_ml_down_saves_untagged_with_null_vectors(client, db, gm, ml_down, caplog):
    owner, cid = gm
    with caplog.at_level(logging.WARNING):
        r = await _save(client, owner, cid, "Borin Stonebeard travelled toward Waterdeep.")
    assert r.status_code == 201, r.text
    assert r.json()["tags"] == []
    row = (await db.execute(sa.select(JournalEntry.embedding, JournalEntry.party_embedding)
                            .where(JournalEntry.id == uuid.UUID(r.json()["id"])))).one()
    assert row.embedding is None and row.party_embedding is None
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("Tag extraction skipped" in rec.getMessage() for rec in warnings)
    assert any("embedding skipped" in rec.getMessage() for rec in warnings)


async def test_journal_save_with_ml_up_tags_and_embeds(client, db, gm):
    owner, cid = gm
    r = await _save(client, owner, cid, "Borin Stonebeard travelled toward Waterdeep.")
    assert r.status_code == 201, r.text
    names = {(t["name"], t["tag_type"]) for t in r.json()["tags"]}
    assert ("Borin Stonebeard", "character") in names and ("Waterdeep", "location") in names
    row = (await db.execute(sa.select(JournalEntry.embedding, JournalEntry.party_embedding)
                            .where(JournalEntry.id == uuid.UUID(r.json()["id"])))).one()
    assert row.embedding is not None and row.party_embedding is not None


# ── The three 503 routes ───────────────────────────────────────────────────

async def test_source_upload_with_ml_down_is_503_and_commits_nothing(client, db, gm, ml_down):
    owner, cid = gm
    r = await client.post("/api/sources/", headers=bearer(owner), data={"campaign_id": str(cid)},
                          files={"file": ("lore.txt", b"The lich sleeps under Karak Dun. " * 40, "text/plain")})
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": "Embedding model unavailable"}
    count = await db.scalar(sa.select(sa.func.count()).select_from(SourceDocument)
                            .where(SourceDocument.campaign_id == cid))
    assert count == 0


async def test_source_upload_with_ml_up_embeds_every_chunk(client, db, gm):
    owner, cid = gm
    r = await client.post("/api/sources/", headers=bearer(owner), data={"campaign_id": str(cid)},
                          files={"file": ("lore.txt", b"The lich sleeps under Karak Dun. " * 40, "text/plain")})
    assert r.status_code == 201, r.text
    assert r.json()["chunk_count"] >= 1
    chunks = (await db.scalars(sa.select(SourceChunk).where(SourceChunk.source_document_id == uuid.UUID(r.json()["id"]))
                               .order_by(SourceChunk.chunk_index))).all()
    assert len(chunks) == r.json()["chunk_count"]
    for chunk in chunks:
        assert list(chunk.embedding) == pytest.approx(fake_vector(chunk.content), abs=1e-5)


async def test_reindex_with_ml_down_is_503_and_changes_nothing(client, db, gm, ml_down):
    owner, cid = gm
    entry = JournalEntry(user_id=owner.id, campaign_id=cid, shorthand="notes", narrative="The tower fell.",
                         entry_hash=uuid.uuid4().hex, embedding=[0.0] * 383 + [1.0])
    db.add(entry)
    await db.commit()
    r = await client.post(f"/api/journals/reindex?campaign_id={cid}", headers=bearer(owner))
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": "Embedding model unavailable"}
    await db.refresh(entry)
    assert entry.embedding is not None and list(entry.embedding)[-1] == pytest.approx(1.0)


async def test_npc_extract_with_ml_down_is_503(client, db, gm, ml_down):
    owner, cid = gm
    db.add(JournalEntry(user_id=owner.id, campaign_id=cid, shorthand="notes", narrative="Mira greeted Borin.",
                        entry_hash=uuid.uuid4().hex))
    await db.commit()
    r = await client.post(f"/api/npcs/extract?campaign_id={cid}", headers=bearer(owner))
    assert r.status_code == 503, r.text
    assert r.json() == {"detail": "NER model unavailable"}


# ── Admin sidecars ─────────────────────────────────────────────────────────

async def _admin(db):
    user = await create_user(db, "mlc_admin")
    user.is_admin = True
    db.add(user)
    await db.commit()
    return user


async def test_sidecars_is_admin_only(client, db):
    user = await create_user(db, "mlc_plain")
    r = await client.get("/api/admin/sidecars", headers=bearer(user))
    assert r.status_code == 403


async def test_sidecars_reports_both_when_up(client, db):
    r = await client.get("/api/admin/sidecars", headers=bearer(await _admin(db)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ml"]["reachable"] is True and body["ml"]["error"] is None
    assert {m["kind"] for m in body["ml"]["models"]} >= {"embedding", "ner"}
    assert body["ml"]["rss_bytes"] == 0 and body["ml"]["resident_budget_mb"] == 2000
    assert body["stt"]["reachable"] is True
    assert body["stt"]["device"] == "cpu" and body["stt"]["compute_type"] == "int8"
    assert body["stt"]["models"][0]["kind"] == "stt"


async def test_sidecars_reports_an_unreachable_one_without_failing(client, db, monkeypatch):
    monkeypatch.setattr(admin_routes, "get_ml_client", lambda: _DownML())
    monkeypatch.setattr(admin_routes, "get_stt_client", lambda: _DownSTT())
    r = await client.get("/api/admin/sidecars", headers=bearer(await _admin(db)))
    assert r.status_code == 200, r.text
    ml, stt = r.json()["ml"], r.json()["stt"]
    assert ml["reachable"] is False and "unreachable" in ml["error"]
    assert ml["models"] == [] and ml["rss_bytes"] is None
    assert stt["reachable"] is False and "stt sidecar unreachable" in stt["error"]


async def test_sidecars_cuts_off_a_stalled_one(client, db, monkeypatch):
    import asyncio

    class Stalled:
        async def status(self):
            await asyncio.sleep(10)

    monkeypatch.setattr(admin_routes, "SIDECAR_STATUS_TIMEOUT_S", 0.05)
    monkeypatch.setattr(admin_routes, "get_stt_client", lambda: Stalled())
    r = await client.get("/api/admin/sidecars", headers=bearer(await _admin(db)))
    assert r.status_code == 200, r.text
    assert r.json()["ml"]["reachable"] is True
    stt = r.json()["stt"]
    assert stt["reachable"] is False and "timed out" in stt["error"]


# ── Eval scoring ───────────────────────────────────────────────────────────

async def test_eval_score_semantic_similarity_is_the_cosine_of_the_ml_vectors():
    from app.services import eval_service

    ref, gen = "The dragon slew the knight.", "A knight fell to the dragon."
    a, b = fake_vector(ref), fake_vector(gen)
    expected = sum(x * y for x, y in zip(a, b)) / (
        sum(x * x for x in a) ** 0.5 * sum(y * y for y in b) ** 0.5)
    score = await eval_service._score(ref, gen)
    assert expected != 0
    assert score["semantic_similarity"] == pytest.approx(expected)


# ── Boot ───────────────────────────────────────────────────────────────────

async def test_lifespan_loads_no_model(monkeypatch):
    from app import main

    init, close = AsyncMock(), AsyncMock()
    monkeypatch.setattr(main, "init_valkey", init)
    monkeypatch.setattr(main, "close_valkey", close)
    monkeypatch.setattr(main, "drain_hooks", AsyncMock())
    monkeypatch.setattr(main.pubsub, "flush_pending", AsyncMock())
    async with main.lifespan(main.app):
        init.assert_awaited_once()
    close.assert_awaited_once()


def test_import_app_main_pulls_in_no_model_package():
    code = ("import sys, app.main; "
            "bad = sorted(m for m in ('spacy', 'sentence_transformers', 'torch', 'transformers') "
            "if m in sys.modules); print(','.join(bad))")
    pythonpath = os.pathsep.join(p for p in (str(BACKEND), os.environ.get("PYTHONPATH", "")) if p)
    env = {**os.environ, "ENVIRONMENT": "test", "PYTHONPATH": pythonpath}
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""
