"""E0-Jobs.8: the file service, the access-checked file route, the stale
marker and files.gc.

Every test gets its own `files_root` (monkeypatched onto the settings), so
a GC pass never sees another test's files. File kinds are test-only derived
types registered for the test and removed after (owning epics add the real
ones)."""
from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import fakeredis
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.access import NotFound, PREVIEW_HEADER, ctx_for, set_visibility
from app.access import files as access_files
from app.access.context import MEMBER_VIEW, audience_ctx
from app.access.files import campaign_files, file_sources, visible_file
from app.access.registry import DERIVED_REGISTRY, register_derived
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.models import Campaign, Genre, User
from app.db.models.campaign_member import CampaignMember
from app.db.models.job import Job
from app.db.models.journal import JournalEntry
from app.db.models.stored_file import DerivedSource, StoredFile
from app.domain.enums import CampaignRole, JobQueue, JobStatus, Visibility
from app.jobs import files_gc
from app.jobs.enqueue import enqueue
from app.jobs.registry import KINDS
from app.schemas.sources import RecordRef, SourceKind, SourceRef
from app.services import file_service as fs

KIND = "test_file"
TREE = "test_tree"
MISSING = "00000000-0000-4000-8000-000000000000"
UPPER = "ABCDEF00-0000-4000-8000-000000000000"
OLD = time.time() - fs.GC_GRACE.total_seconds() - 3600


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    path = tmp_path / "files"
    path.mkdir()
    monkeypatch.setattr(get_settings(), "files_root", str(path))
    return path


@pytest.fixture(autouse=True)
def file_types():
    saved = list(DERIVED_REGISTRY)
    register_derived(KIND, ["journal"])
    register_derived(TREE, ["journal"])
    yield
    DERIVED_REGISTRY[:] = saved


async def _user(db, label: str) -> User:
    user = User(email=f"fs-{label}-{uuid.uuid4().hex[:12]}@example.com", hashed_password="x",
                display_name=label, access_granted=True, access_source="promo")
    db.add(user)
    await db.flush()
    return user


class World:
    def __init__(self, owner, player, campaign, party, gm, player_entry):
        self.owner, self.player, self.campaign = owner, player, campaign
        self.party, self.gm, self.player_entry = party, gm, player_entry

    @property
    def cid(self):
        return self.campaign.id


async def _entry(db, cid, author, visibility: str, kind: str = "gm") -> JournalEntry:
    e = JournalEntry(user_id=author, campaign_id=cid, shorthand="s", narrative="n", entry_hash=uuid.uuid4().hex,
                     kind=kind, visibility=visibility)
    db.add(e)
    await db.flush()
    return e


async def _world(db) -> World:
    owner = await _user(db, "owner")
    player = await _user(db, "player")
    c = Campaign(user_id=owner.id, name="Files", genre=Genre.fantasy)
    db.add(c)
    await db.flush()
    db.add(CampaignMember(campaign_id=c.id, user_id=player.id, role=CampaignRole.PLAYER))
    party = await _entry(db, c.id, owner.id, "party")
    gm = await _entry(db, c.id, owner.id, "gm")
    player_entry = await _entry(db, c.id, player.id, "party", kind="player")
    await db.commit()
    return World(owner, player, c, party, gm, player_entry)


@pytest.fixture
async def world(db) -> World:
    return await _world(db)


async def gm_ctx(db, w: World):
    return await ctx_for(db, w.owner.id, w.cid)


async def player_ctx(db, w: World):
    return await ctx_for(db, w.player.id, w.cid)


def ref(entry, field: str | None = "narrative") -> SourceRef:
    return SourceRef(kind=SourceKind.JOURNAL, id=entry.id, field=field)


async def _put(db, w: World, sources, *, data=b"hello", content_type="audio/mpeg", cache_key=None,
               commit=True, kind=KIND) -> StoredFile:
    row = await fs.put(db, await gm_ctx(db, w), w.cid, kind, data, content_type, cache_key=cache_key,
                       sources=sources)
    if commit:
        await db.commit()
    return row


def _files_under(root) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


# ── put / put_tree ─────────────────────────────────────────────────────────

async def test_put_writes_bytes_row_and_sources(db, world, root):
    row = await _put(db, world, [ref(world.party), ref(world.party, "shorthand")], data=b"abc")
    assert row.storage_key.startswith(f"{world.cid}/{KIND}/")
    assert (root / row.storage_key).read_bytes() == b"abc"
    assert (row.size, row.sha256, row.content_type, row.stale) == (3, hashlib.sha256(b"abc").hexdigest(),
                                                                    "audio/mpeg", False)
    pairs = await file_sources(db, row)
    assert {(ds.derived_type, ds.derived_id, ds.ref_kind, ds.ref_id, ds.ref_field) for ds, _ in pairs} == {
        (KIND, row.id, "journal", world.party.id, "narrative"), (KIND, row.id, "journal", world.party.id, "shorthand")}
    assert [ds.id for ds, _ in pairs] == sorted(ds.id for ds, _ in pairs)
    assert all(src is not None and src.id == world.party.id for _, src in pairs)
    assert not [p for p in root.rglob(f"{fs.TMP_PREFIX}*")]


async def test_file_sources_returns_every_row_and_one_hidden_source_hides_the_file(db, world):
    sources = [ref(world.party), ("journal", uuid.uuid4(), None), ref(world.gm),
               {"ref_kind": "nope", "ref_id": world.party.id}]
    row = await _put(db, world, sources)
    pairs = await file_sources(db, row)
    assert len(pairs) == 4  # no visibility filter, no limit
    by_kind = {(ds.ref_kind, ds.ref_id): src for ds, src in pairs}
    assert by_kind[("journal", world.party.id)].id == world.party.id
    assert by_kind[("journal", world.gm.id)].id == world.gm.id
    assert by_kind[("nope", world.party.id)] is None
    assert sum(1 for _, src in pairs if src is None) == 2
    with pytest.raises(NotFound):
        await visible_file(db, await player_ctx(db, world), row.id)
    assert (await visible_file(db, await gm_ctx(db, world), row.id)).id == row.id


@pytest.mark.parametrize("content_type", [
    "text/html", "TEXT/HTML; charset=utf-8", "image/svg+xml", "application/xml", "text/xml",
    "application/xhtml+xml", "application/javascript", "text/javascript", "application/atom+xml",
    "inode/directory", "not a type", "text/plain\r\nX-Evil: 1",
])
async def test_put_refuses_active_or_malformed_types(db, world, root, content_type):
    with pytest.raises(ValueError):
        await _put(db, world, [ref(world.party)], content_type=content_type)
    assert _files_under(root) == []


async def test_put_refuses_a_ctx_of_another_campaign_or_a_reduced_one(db, world):
    other = await _world(db)
    with pytest.raises(NotFound):
        await fs.put(db, await gm_ctx(db, other), world.cid, KIND, b"x", "audio/mpeg")
    reduced = audience_ctx(world.cid, MEMBER_VIEW, by=await gm_ctx(db, world))
    with pytest.raises(NotFound):
        await fs.put(db, reduced, world.cid, KIND, b"x", "audio/mpeg")
    with pytest.raises(ValueError):
        await fs.put(db, await gm_ctx(db, world), world.cid, "../etc", b"x", "audio/mpeg")


async def test_put_bytes_are_unlinked_on_rollback(db, world, root):
    row = await _put(db, world, [ref(world.party)], commit=False)
    path = root / row.storage_key
    assert path.is_file()
    await db.rollback()
    assert not path.exists()


async def test_put_bytes_are_unlinked_when_a_savepoint_rolls_back(db, world, root):
    kept = await _put(db, world, [ref(world.party)], commit=False)
    ctx = await gm_ctx(db, world)
    with pytest.raises(RuntimeError):
        async with db.begin_nested():
            dropped = await fs.put(db, ctx, world.cid, KIND, b"x", "audio/mpeg", sources=[ref(world.party)])
            dropped_path = root / dropped.storage_key
            assert dropped_path.is_file()
            raise RuntimeError("roll the savepoint back")
    assert not dropped_path.exists()
    await db.commit()
    assert (root / kept.storage_key).is_file()


async def test_a_reused_cache_key_supersedes_the_fresh_file(db, world):
    old = await _put(db, world, [ref(world.party)], cache_key="recap:1")
    new = await _put(db, world, [ref(world.party)], cache_key="recap:1")
    rows = {r.id: r for r in await campaign_files(db, await gm_ctx(db, world))}
    assert rows[old.id].stale is True and rows[new.id].stale is False


async def test_put_tree_writes_one_row_by_rename(db, world, root):
    files = [("z/0/0.jpg", b"j0"), ("z/1/0.jpg", b"j10"), ("meta.json", b"{}")]
    row = await fs.put_tree(db, await gm_ctx(db, world), TREE, files, sources=[ref(world.party)])
    await db.commit()
    base = root / row.storage_key
    assert base.is_dir() and not [p for p in base.parent.iterdir() if p.name.startswith(fs.TMP_PREFIX)]
    manifest = (base / fs.MANIFEST_NAME).read_bytes()
    assert row.sha256 == hashlib.sha256(manifest).hexdigest()
    assert row.size == 2 + 3 + 2 and row.content_type == fs.TREE_CONTENT_TYPE
    assert json.loads(manifest) == {"files": [["meta.json", 2, hashlib.sha256(b"{}").hexdigest()],
                                              ["z/0/0.jpg", 2, hashlib.sha256(b"j0").hexdigest()],
                                              ["z/1/0.jpg", 3, hashlib.sha256(b"j10").hexdigest()]]}
    r = fs.accel_response(row, "z/0/0.jpg")
    assert r.headers["x-accel-redirect"] == f"/_files/{row.storage_key}/z/0/0.jpg"
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["content-disposition"] == 'inline; filename="0.jpg"'
    assert fs.accel_response(row, "meta.json").headers["content-disposition"] == 'attachment; filename="meta.json"'
    for bad in ("../x", "/etc/passwd", "a\\b", "z/0/9.jpg", fs.MANIFEST_NAME, "z/../meta.json", "z//0.jpg", "",
                "z/0/0.jpg\x00", None):
        with pytest.raises(NotFound):
            fs.accel_response(row, bad)
    assert await fs.read_bytes(db, await player_ctx(db, world), row.id, "z/1/0.jpg") == b"j10"


@pytest.mark.parametrize("files", [
    [], [("index.html", b"x")], [("a.svg", b"x")], [("a.js", b"x")], [(".hidden", b"x")],
    [("a.jpg", b"x"), ("a.jpg", b"y")], [("a", b"x"), ("a/b.jpg", b"y")], [("../a.jpg", b"x")],
])
async def test_put_tree_refuses_bad_trees(db, world, root, files):
    with pytest.raises((ValueError, TypeError)):
        await fs.put_tree(db, await gm_ctx(db, world), TREE, files, sources=[ref(world.party)])
    assert _files_under(root) == []


async def test_put_tree_is_unlinked_on_rollback(db, world, root):
    row = await fs.put_tree(db, await gm_ctx(db, world), TREE, [("a.jpg", b"x")], sources=[ref(world.party)])
    base = root / row.storage_key
    assert base.is_dir()
    await db.rollback()
    assert not base.exists()


async def test_a_tree_with_a_tampered_manifest_serves_nothing(db, world, root):
    row = await fs.put_tree(db, await gm_ctx(db, world), TREE, [("a.jpg", b"x")], sources=[ref(world.party)])
    await db.commit()
    (root / row.storage_key / fs.MANIFEST_NAME).write_bytes(b'{"files":[["a.jpg",1,"' + b"0" * 64 + b'"]]}')
    with pytest.raises(NotFound):
        fs.accel_response(row, "a.jpg")
    with pytest.raises(NotFound):
        await fs.open(db, await gm_ctx(db, world), row.id)


# ── delete ─────────────────────────────────────────────────────────────────

async def _row_count(db, model, *where) -> int:
    return (await db.execute(sa.select(sa.func.count()).select_from(model).where(*where))).scalar_one()


@pytest.mark.parametrize("tree", [False, True])
async def test_delete_removes_rows_then_bytes_after_commit(db, world, root, tree):
    ctx = await gm_ctx(db, world)
    if tree:
        row = await fs.put_tree(db, ctx, TREE, [("z/0/0.jpg", b"x"), ("z/0/1.jpg", b"y")],
                                sources=[ref(world.party), ref(world.gm)])
    else:
        row = await fs.put(db, ctx, world.cid, KIND, b"x", "audio/mpeg", sources=[ref(world.party), ref(world.gm)])
    await db.commit()
    path = root / row.storage_key
    file_id = row.id
    await fs.delete(db, ctx, row)
    assert path.exists()  # not before the commit
    await db.commit()
    assert not path.exists()
    assert await _row_count(db, StoredFile, StoredFile.id == file_id) == 0
    assert await _row_count(db, DerivedSource, DerivedSource.derived_id == file_id) == 0


async def test_delete_rolled_back_keeps_the_bytes(db, world, root):
    row = await _put(db, world, [ref(world.party)])
    path = root / row.storage_key
    await fs.delete(db, await gm_ctx(db, world), row)
    await db.rollback()
    assert path.is_file()


async def test_delete_needs_a_gm_of_the_files_campaign(db, world):
    row = await _put(db, world, [ref(world.party)])
    with pytest.raises(NotFound):
        await fs.delete(db, await player_ctx(db, world), row)
    other = await _world(db)
    with pytest.raises(NotFound):
        await fs.delete(db, await gm_ctx(db, other), row)


# ── The stale marker ───────────────────────────────────────────────────────

async def _stale(db, file_id) -> bool:
    return (await db.execute(sa.select(StoredFile.stale).where(StoredFile.id == file_id))).scalar_one()


async def test_a_downgrade_marks_files_stale_in_the_same_transaction(db, world):
    row = await _put(db, world, [ref(world.party)])
    unrelated = await _put(db, world, [ref(world.gm)])
    player = await player_ctx(db, world)
    assert (await visible_file(db, player, row.id)).id == row.id
    await set_visibility(db, await gm_ctx(db, world), RecordRef(kind="journal", id=world.party.id), Visibility.GM)
    assert await _stale(db, row.id) is True  # before any commit
    assert await _stale(db, unrelated.id) is False
    await db.commit()
    with pytest.raises(NotFound):
        await visible_file(db, player, row.id)
    assert (await fs.open(db, await gm_ctx(db, world), row.id)).id == row.id  # the GM still has it


async def test_the_marker_matches_on_the_id_whatever_the_visibility_kind(db, world):
    # player_journal is a Visibility kind; the stored ref_kind is `journal`.
    file_id = (await _put(db, world, [("journal", world.player_entry.id, "narrative")])).id
    await set_visibility(db, await gm_ctx(db, world), RecordRef(kind="player_journal", id=world.player_entry.id),
                         Visibility.GM)
    assert await _stale(db, file_id) is True
    await db.rollback()
    assert await _stale(db, file_id) is False  # rolled back with the change


# ── Headers ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content_type, inline", [
    ("audio/mpeg", True), ("audio/ogg", True), ("image/png", True), ("image/jpeg", True), ("application/pdf", False),
    ("text/plain", True), ("application/zip", False), ("application/json", False), ("video/mp4", False),
])
async def test_accel_response_headers(db, world, content_type, inline):
    row = await _put(db, world, [ref(world.party)], content_type=content_type, data=b"bytes")
    r = fs.accel_response(row, access_epoch=7)
    assert r.status_code == 200 and r.body == b""
    assert r.headers["x-accel-redirect"] == f"/_files/{row.storage_key}"
    assert r.headers["content-type"] == content_type
    assert r.headers["cache-control"] == "private, no-cache"
    assert r.headers["etag"] == f'"{hashlib.sha256(b"bytes").hexdigest()[:32]}-e7"'
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "default-src 'none'; sandbox"
    ext = mimetypes.guess_extension(content_type, strict=False) or ""
    assert r.headers["content-disposition"] == (
        f'{"inline" if inline else "attachment"}; filename="{KIND}-{row.id}{ext}"')
    with pytest.raises(NotFound):
        fs.accel_response(row, "a/subpath")


def test_download_names_keep_only_safe_characters():
    row = StoredFile(id=uuid.UUID(MISSING), kind=KIND)
    assert fs.download_name(row, "application/x-weird") == f"{KIND}-{MISSING}"
    assert fs.download_name(row, "image/png", "z/0/a b\"c.png") == "a_b_c.png"
    assert fs.disposition("text/plain", 'x"; y=1') == 'inline; filename="x___y_1"'


@pytest.mark.parametrize("stored", ["text/html", "image/svg+xml", "application/javascript", "garbage"])
async def test_an_active_row_is_served_as_an_octet_stream_attachment(world, root, stored):
    key = fs.new_storage_key(world.cid, KIND)
    (root / key).parent.mkdir(parents=True)
    (root / key).write_bytes(b"<script>")
    row = StoredFile(id=uuid.uuid4(), campaign_id=world.cid, kind=KIND, storage_key=key, content_type=stored,
                     size=8, sha256=hashlib.sha256(b"<script>").hexdigest())
    r = fs.accel_response(row)
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == f'attachment; filename="{KIND}-{row.id}.bin"'


@pytest.mark.parametrize("key", [
    "../x", "/etc/passwd", "a\\b", "x\x00y", "", None, f"{MISSING}/{KIND}", f"{MISSING}/../{MISSING}",
    f"{MISSING}/{KIND}/{MISSING}/extra", f"{MISSING}/Bad Kind/{MISSING}", f"{UPPER}/{KIND}/{MISSING}",
])
def test_key_path_rejects_unsafe_keys(key):
    with pytest.raises(fs.UnsafePath):
        fs.key_path(key)


def test_key_path_refuses_a_symlink_out_of_the_root(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / MISSING).symlink_to(outside, target_is_directory=True)
    with pytest.raises(fs.UnsafePath):
        fs.key_path(f"{MISSING}/{KIND}/{MISSING}")


async def test_a_sql_python_mismatch_is_a_404_and_a_warning(db, world, monkeypatch, caplog):
    row = await _put(db, world, [ref(world.party)])
    player = await player_ctx(db, world)
    assert (await visible_file(db, player, row.id)).id == row.id
    from app.access.audience import GM_AUDIENCE

    monkeypatch.setattr(access_files, "audience_of", lambda obj, parents=None: GM_AUDIENCE)
    with caplog.at_level(logging.WARNING, logger="app.access.files"), pytest.raises(NotFound):
        await visible_file(db, player, row.id)
    assert "file_visibility_mismatch" in caplog.text


# ── GET /api/files/{file_id}: the matrix ───────────────────────────────────

def _auth(user, preview: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {create_access_token(str(user.id))}"}
    if preview:
        headers[PREVIEW_HEADER] = "member"
    return headers


def _comparable(r) -> tuple:
    return r.status_code, r.content, sorted((k, v) for k, v in r.headers.items()
                                            if k not in ("date", "x-response-time", "server"))


async def test_route_matrix(db, client, world, root):
    other = await _world(db)
    visible = await _put(db, world, [ref(world.party)])
    hidden = {
        "gm_only_source": await _put(db, world, [ref(world.party), ref(world.gm)]),
        "gm_field": await _put(db, world, [ref(world.party, "shorthand")]),
        "unknown_ref_kind": await _put(db, world, [("unregistered_kind", world.party.id, None)]),
        "no_sources": await _put(db, world, []),
        "stale": await _put(db, world, [ref(world.party)]),
        "unregistered_type": await _put(db, world, [ref(world.party)], kind="unregistered_type"),
    }
    await db.execute(sa.update(StoredFile).where(StoredFile.id == hidden["stale"].id).values(stale=True))
    await db.commit()
    gone = await _put(db, world, [ref(world.party)])
    os.unlink(root / gone.storage_key)
    elsewhere = await _put(db, other, [ref(other.party)])

    missing = await client.get(f"/api/files/{MISSING}", headers=_auth(world.player))
    assert missing.status_code == 404 and missing.json() == {"detail": "Not found"}
    assert "Authorization" in missing.headers["vary"] and PREVIEW_HEADER in missing.headers["vary"]

    ok = await client.get(f"/api/files/{visible.id}", headers=_auth(world.player))
    assert ok.status_code == 200 and ok.content == b"", ok.text
    assert ok.headers["x-accel-redirect"] == f"/_files/{visible.storage_key}"
    assert ok.headers["cache-control"] == "private, no-cache"

    for label, row in [*hidden.items(), ("bytes_missing", gone), ("other_campaign", elsewhere)]:
        r = await client.get(f"/api/files/{row.id}", headers=_auth(world.player))
        assert _comparable(r) == _comparable(missing), label
    for bad in ("not-a-uuid", "1", MISSING.replace("-", "")):
        r = await client.get(f"/api/files/{bad}", headers=_auth(world.player))
        assert _comparable(r) == _comparable(missing), bad

    # The GM: fresh and stale alike (not an unregistered type's either: GM sees everything).
    for row in (visible, hidden["stale"], hidden["gm_only_source"], hidden["no_sources"]):
        r = await client.get(f"/api/files/{row.id}", headers=_auth(world.owner))
        assert r.status_code == 200 and r.headers["x-accel-redirect"] == f"/_files/{row.storage_key}"
    gm_gone = await client.get(f"/api/files/{gone.id}", headers=_auth(world.owner))
    gm_missing = await client.get(f"/api/files/{MISSING}", headers=_auth(world.owner))
    assert _comparable(gm_gone) == _comparable(gm_missing)

    # Preview narrows the GM to the member view.
    preview_missing = await client.get(f"/api/files/{MISSING}", headers=_auth(world.owner, preview=True))
    for row in (hidden["gm_only_source"], hidden["stale"]):
        r = await client.get(f"/api/files/{row.id}", headers=_auth(world.owner, preview=True))
        assert _comparable(r) == _comparable(preview_missing)
    assert (await client.get(f"/api/files/{visible.id}", headers=_auth(world.owner, preview=True))).status_code == 200


async def test_route_if_none_match_is_304_without_accel(db, client, world):
    row = await _put(db, world, [ref(world.party)])
    first = await client.get(f"/api/files/{row.id}", headers=_auth(world.player))
    tag = first.headers["etag"]
    assert tag.endswith('-e0"')
    r = await client.get(f"/api/files/{row.id}", headers={**_auth(world.player), "If-None-Match": tag})
    assert r.status_code == 304 and "x-accel-redirect" not in r.headers and r.content == b""
    r = await client.get(f"/api/files/{row.id}", headers={**_auth(world.player), "If-None-Match": '"other-e0"'})
    assert r.status_code == 200


async def test_route_etag_follows_the_access_epoch(db, client, world):
    row = await _put(db, world, [ref(world.party)])
    before = (await client.get(f"/api/files/{row.id}", headers=_auth(world.player))).headers["etag"]
    await db.execute(sa.update(CampaignMember).where(CampaignMember.user_id == world.player.id)
                     .values(access_epoch=CampaignMember.access_epoch + 1))
    await db.commit()
    after = (await client.get(f"/api/files/{row.id}", headers=_auth(world.player))).headers["etag"]
    assert before.endswith('-e0"') and after.endswith('-e1"') and before[:33] == after[:33]


async def test_the_app_has_no_files_route_outside_api(client, world):
    r = await client.get(f"/_files/{world.cid}/{KIND}/{MISSING}")
    assert r.status_code == 404


# ── files.gc ───────────────────────────────────────────────────────────────

def test_files_gc_is_registered():
    kind = KINDS["files.gc"]
    assert kind.queue == JobQueue.BACKFILL and kind.resources == frozenset() and kind.live_safe
    assert kind.handler == "app.jobs.files_gc:handle"


async def _gc_setup(db, world, root):
    old = await _put(db, world, [ref(world.party)], cache_key="k")
    new = await _put(db, world, [ref(world.party)], cache_key="k")
    tree_old = await fs.put_tree(db, await gm_ctx(db, world), TREE, [("a.jpg", b"1")], sources=[ref(world.party)],
                                 cache_key="t")
    await db.commit()
    tree_new = await fs.put_tree(db, await gm_ctx(db, world), TREE, [("a.jpg", b"2")], sources=[ref(world.party)],
                                 cache_key="t")
    await db.commit()
    downgraded = await _put(db, world, [ref(world.party)], cache_key="d")
    await db.execute(sa.update(StoredFile).where(StoredFile.id == downgraded.id).values(stale=True))
    await db.commit()
    stray_old = root / str(world.cid) / KIND / str(uuid.uuid4())
    stray_old.write_bytes(b"no row")
    os.utime(stray_old, (OLD, OLD))
    tmp_old = root / str(world.cid) / TREE / f"{fs.TMP_PREFIX}{uuid.uuid4()}"
    (tmp_old / "z").mkdir(parents=True)
    (tmp_old / "z" / "a.jpg").write_bytes(b"half a tree")
    os.utime(tmp_old, (OLD, OLD))
    stray_young = root / str(world.cid) / KIND / str(uuid.uuid4())
    stray_young.write_bytes(b"in flight")
    dead = root / str(uuid.uuid4())
    (dead / KIND).mkdir(parents=True)
    (dead / KIND / str(uuid.uuid4())).write_bytes(b"deleted campaign")
    os.utime(dead, (OLD, OLD))
    dead_young = root / str(uuid.uuid4())
    dead_young.mkdir()
    marker = root / str(world.cid) / ".backup-live-audio"
    marker.write_bytes(b"")
    os.utime(marker, (OLD, OLD))
    return dict(old=old, new=new, tree_old=tree_old, tree_new=tree_new, downgraded=downgraded, stray_old=stray_old,
                tmp_old=tmp_old, stray_young=stray_young, dead=dead, dead_young=dead_young, marker=marker)


async def test_gc_candidates(db, world, root):
    s = await _gc_setup(db, world, root)
    cands = await fs.gc_candidates(db, await gm_ctx(db, world))
    got = {(c.action, c.target) for c in cands}
    assert got == {
        (fs.CAMPAIGN_DIR, s["dead"].name),
        (fs.ORPHAN, str(s["stray_old"].relative_to(root))),
        (fs.ORPHAN, str(s["tmp_old"].relative_to(root))),
        (fs.SUPERSEDED, str(s["old"].id)),
        (fs.SUPERSEDED, str(s["tree_old"].id)),
    }
    assert [c.key for c in cands] == sorted(c.key for c in cands)
    with pytest.raises(NotFound):
        await fs.gc_candidates(db, await player_ctx(db, world))


async def test_files_gc_job_removes_superseded_rowless_and_deleted_campaign_files(db, world, root):
    s = await _gc_setup(db, world, root)
    ctx = await gm_ctx(db, world)
    job_id = await enqueue(db, ctx, "files.gc", {}, idempotency_key=files_gc.gc_key(world.cid))
    await db.commit()  # JOBS_EAGER: every cursor step runs here
    job = (await db.execute(sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True))
           ).scalar_one()
    assert job.status == JobStatus.DONE, (job.status, job.error_code, job.error_message)
    left = {r.id for r in await campaign_files(db, ctx)}
    assert s["old"].id not in left and s["tree_old"].id not in left
    assert {s["new"].id, s["tree_new"].id, s["downgraded"].id} <= left
    assert not (root / s["old"].storage_key).exists() and not (root / s["tree_old"].storage_key).exists()
    for name in ("new", "tree_new", "downgraded"):
        assert (root / s[name].storage_key).exists(), name
    assert not s["stray_old"].exists() and not s["tmp_old"].exists() and not s["dead"].exists()
    assert s["stray_young"].exists() and s["dead_young"].exists() and s["marker"].exists()
    assert await _row_count(db, DerivedSource, DerivedSource.derived_id == s["old"].id) == 0


async def test_gc_one_skips_what_no_longer_qualifies(db, world, root):
    s = await _gc_setup(db, world, root)
    ctx = await gm_ctx(db, world)
    # The fresh file was deleted meanwhile: the old one is no longer superseded.
    await fs.delete(db, ctx, s["new"])
    await db.commit()
    assert not await fs.gc_one(db, ctx, fs.GcCandidate("3:x", fs.SUPERSEDED, str(s["old"].id)))
    # Another Campaign's entry is never this Job's to remove.
    other = await _world(db)
    stray = root / str(other.cid) / KIND / str(uuid.uuid4())
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"x")
    os.utime(stray, (OLD, OLD))
    assert not await fs.gc_one(db, ctx, fs.GcCandidate("2:x", fs.ORPHAN, str(stray.relative_to(root))))
    assert stray.exists()
    # A live Campaign's directory is never swept as a deleted one.
    assert not await fs.gc_one(db, ctx, fs.GcCandidate("1:x", fs.CAMPAIGN_DIR, str(other.cid)))
    assert not await fs.gc_one(db, ctx, fs.GcCandidate("2:x", fs.ORPHAN, f"{world.cid}/{KIND}/.."))
    assert not await fs.gc_one(db, ctx, fs.GcCandidate("1:x", fs.CAMPAIGN_DIR, "../etc"))


async def test_schedule_daily_enqueues_once_per_day_per_campaign_directory(db, world, root, monkeypatch):
    other = await _world(db)  # no directory: no Job
    await _put(db, world, [ref(world.party)])
    (root / str(uuid.uuid4())).mkdir()  # a deleted Campaign's directory: no Job of its own
    redis = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    now = datetime(2026, 11, 1, 23, 59, tzinfo=timezone.utc)
    jobs = await files_gc.schedule_daily(factory, redis, now=now)
    assert len(jobs) == 1
    job = (await db.execute(sa.select(Job).where(Job.id == jobs[0]))).scalar_one()
    assert (job.kind, job.campaign_id, job.idempotency_key, job.created_by) == (
        "files.gc", world.cid, f"files.gc:{world.cid}", world.owner.id)
    assert await files_gc.schedule_daily(factory, redis, now=now) == []
    assert len(await files_gc.schedule_daily(factory, redis, now=now + timedelta(minutes=2))) == 1
    assert other.cid not in {j.campaign_id for j in (await db.execute(
        sa.select(Job).where(Job.kind == "files.gc", Job.campaign_id == other.cid))).scalars()}


def test_nginx_serves_files_only_through_an_internal_location():
    from tests.ev4 import nginx

    loc = nginx.https_locations().resolve(f"/_files/{MISSING}/{KIND}/{MISSING}/z/0/0.jpg")
    assert loc is not None and loc.uri == "/_files/" and loc.modifier == nginx.NOREGEX
    directives = {(d.name, *d.args) for d in loc.directives}
    assert {("internal",), ("alias", "/data/files/"), ("etag", "off"), ("if_modified_since", "off")} <= directives
    headers = {d.args[0]: d.args[1] for d in loc.directives if d.name == "add_header"}
    assert headers["ETag"] == "$upstream_http_etag" and headers["Vary"] == "$upstream_http_vary"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Security-Policy"] == fs.CSP
    # A static-asset regex can never take a stored file (`^~`).
    assert nginx.https_locations().resolve(f"/_files/{MISSING}/x.js").uri == "/_files/"


# ── Review follow-ups ──────────────────────────────────────────────────────

def test_a_trailing_newline_is_never_a_valid_name(root):
    with pytest.raises(fs.UnsafePath):
        fs.check_subpath("a.jpg\n")
    with pytest.raises(fs.UnsafePath):
        fs.key_path(f"{MISSING}/{KIND}/{MISSING}\n")
    assert fs.check_content_type("audio/mpeg\n") == "audio/mpeg"  # stored without it
    (root / f"{MISSING}\n").mkdir()
    (root / MISSING).mkdir()
    assert fs.campaign_dirs() == [uuid.UUID(MISSING)]


async def test_an_unsafe_old_entry_name_does_not_fail_the_gc_job(db, world, root):
    kept = await _put(db, world, [ref(world.party)])
    weird = root / str(world.cid) / KIND / "bad\\name"
    weird.write_bytes(b"x")
    os.utime(weird, (OLD, OLD))
    ctx = await gm_ctx(db, world)
    job_id = await enqueue(db, ctx, "files.gc", {}, idempotency_key=files_gc.gc_key(world.cid))
    await db.commit()
    job = (await db.execute(sa.select(Job).where(Job.id == job_id).execution_options(populate_existing=True))
           ).scalar_one()
    assert job.status == JobStatus.DONE, (job.status, job.error_code)
    assert (root / kept.storage_key).exists()


async def test_schedule_daily_clears_the_day_key_when_it_fails(db, world, root, monkeypatch):
    await _put(db, world, [ref(world.party)])
    redis = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    now = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

    async def boom(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(files_gc, "campaign_owners", boom)
    with pytest.raises(RuntimeError):
        await files_gc.schedule_daily(factory, redis, now=now)
    assert not redis.exists(files_gc.day_key(now))
    monkeypatch.undo()
    monkeypatch.setattr(get_settings(), "files_root", str(root))
    assert len(await files_gc.schedule_daily(factory, redis, now=now)) == 1


async def test_schedule_daily_sweeps_deleted_campaigns_when_no_live_one_has_a_directory(db, world, root, monkeypatch):
    dead = root / str(uuid.uuid4())
    dead.mkdir()
    os.utime(dead, (OLD, OLD))
    first = next(iter(await files_gc.campaign_owners(db, created_before=None)))
    redis = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    jobs = await files_gc.schedule_daily(async_sessionmaker(db.bind, expire_on_commit=False), redis)
    assert len(jobs) == 1
    job = (await db.execute(sa.select(Job).where(Job.id == jobs[0]).execution_options(populate_existing=True))
           ).scalar_one()
    assert job.campaign_id == first and job.status == JobStatus.DONE
    assert not dead.exists()


async def test_a_players_put_never_supersedes_the_gms_file(db, world):
    gm_file = await _put(db, world, [ref(world.party)], cache_key="shared")
    player = await player_ctx(db, world)
    mine = await fs.put(db, player, world.cid, KIND, b"mine", "audio/mpeg", cache_key="shared",
                        sources=[ref(world.party)])
    await db.commit()
    assert mine.audience_owner_id == world.player.id and mine.cache_key == f"{world.player.id}:shared"
    again = await fs.put(db, player, world.cid, KIND, b"mine 2", "audio/mpeg", cache_key="shared",
                         sources=[ref(world.party)])
    await db.commit()
    assert await _stale(db, mine.id) is True and await _stale(db, again.id) is False  # their own one is
    assert await _stale(db, gm_file.id) is False
    with pytest.raises(ValueError):
        await fs.put(db, player, world.cid, KIND, b"x", "audio/mpeg", audience_owner_id=world.owner.id)


async def test_a_reaper_pass_schedules_files_gc(db, world, monkeypatch):
    import asyncio

    from app.jobs import worker
    from tests.conftest import TEST_DB_URL

    monkeypatch.setattr(get_settings(), "database_url", TEST_DB_URL)
    monkeypatch.setattr(get_settings(), "jobs_eager", False)  # leave the Job queued to look at
    from app.jobs import outbox

    await _put(db, world, [ref(world.party)])
    connection = fakeredis.FakeRedis(server=fakeredis.FakeServer())
    outbox.set_connection(connection)  # the Job's after-commit push
    try:
        reaper = worker.Reaper("files", connection=connection)
        assert await asyncio.to_thread(reaper.tick) is not None
    finally:
        outbox.set_connection(None)
    job = (await db.execute(sa.select(Job).where(Job.kind == "files.gc", Job.campaign_id == world.cid)
                            .execution_options(populate_existing=True))).scalar_one()
    assert job.idempotency_key == f"files.gc:{world.cid}"


async def test_a_put_on_a_session_closed_without_commit_leaves_no_bytes(db, world, root):
    factory = async_sessionmaker(db.bind, expire_on_commit=False)
    ctx = await gm_ctx(db, world)
    session = factory()
    row = await fs.put(session, ctx, world.cid, KIND, b"x", "audio/mpeg", sources=[ref(world.party)])
    path = root / row.storage_key
    assert path.is_file()
    await session.close()
    assert not path.exists()


async def test_read_bytes_refuses_bytes_changed_on_disk(db, world, root, caplog):
    row = await _put(db, world, [ref(world.party)], data=b"original")
    player = await player_ctx(db, world)
    assert await fs.read_bytes(db, player, row.id) == b"original"
    (root / row.storage_key).write_bytes(b"tampered")
    with caplog.at_level(logging.WARNING, logger="app.services.file_service"), pytest.raises(NotFound):
        await fs.read_bytes(db, player, row.id)
    assert "file_hash_mismatch" in caplog.text
