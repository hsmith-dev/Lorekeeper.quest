"""The file service: the only code that touches the `files_data` volume
(E0-Jobs.8, AD-14, AR-14).

    row = await file_service.put(db, ctx, ctx.campaign_id, "recap_audio", data, "audio/mpeg",
                                 cache_key=f"recap:{recap.id}:{recap.version}",
                                 sources=[SourceRef(kind="journal", id=entry.id, field="narrative")])
    tree = await file_service.put_tree(db, ctx, "map_tiles", [("z/0/0.jpg", jpeg), ...], sources=[...])
    await db.commit()                     # the bytes are kept; on rollback they are unlinked

    row = await file_service.open(db, ctx, file_id)          # access check + bytes present, else 404
    return file_service.accel_response(row, access_epoch=ctx.access_epoch, request=request)

**Layout.** Bytes live under `settings.files_root` (`/data/files`, the
`files_data` volume) at a generated `storage_key` of
`{campaign_id}/{kind}/{uuid4}`: a file, or for `put_tree` a directory
holding the tree and its `.manifest.json`. Every key and tree subpath is
validated (regex segments, no `..`, no absolute path, no backslash or NUL,
the real path stays under `files_root`) before it reaches the filesystem or
a header. A file is written to a temporary name and renamed into place; a
tree is built in a temporary directory and renamed, so no reader ever sees
half of one.

**Rows.** `put`/`put_tree` insert one `stored_files` row and one
`derived_sources` row per source in the caller's transaction (they never
commit). A `cache_key` already held by a fresh file of the same Campaign,
kind and `audience_owner_id` marks that file stale (superseded) first. A
non-GM ctx always stores its own file (`audience_owner_id` = its user), and
an owned file's stored `cache_key` is `<owner id>:<cache_key>`. The bytes written for a row
that never commits are unlinked when the transaction (or the savepoint) rolls
back; `delete` removes the rows in the caller's transaction and unlinks the
bytes only after the root transaction commits.

**Content types.** `put` refuses HTML, SVG, XML, XHTML and JavaScript
(ValueError), and `put_tree` refuses tree entries whose extension maps to
one. `accel_response` serves any such row as `application/octet-stream` +
`attachment` anyway, and every response carries `nosniff` and a sandboxing
CSP, so a stored file can never run script on the app's origin.

**Staleness.** `mark_files_stale` is a registered stale marker: any
Visibility change of a source marks every non-stale file deriving from it
stale, in the same transaction. A non-GM never gets a stale file
(app/access/registry.py); a GM still does.

**GC.** The `files.gc` Job (app/jobs/files_gc.py) walks `gc_candidates` for
one Campaign with `run_cursor`: superseded files (stale, with a fresh file
holding the same `cache_key` and owner), row-less entries in the Campaign's directory
older than GC_GRACE, and the directories of deleted Campaigns older than
GC_GRACE. A file made stale by a downgrade is not superseded: the GM can
still fetch it, so it stays until it is regenerated or deleted.

Reads of `stored_files`/`derived_sources` live in app/access/files.py
(CI-8); this module writes with `insert`/`update`/`delete` and the ORM.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import sqlalchemy as sa
from fastapi import Request
from fastapi.responses import Response
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.access.context import CampaignContext
from app.access.files import campaign_files, files_derived_from, visible_file
from app.access.owners import campaign_owners
from app.access.policy import GM, NotFound, not_found
from app.access.visibility import register_stale_marker
from app.core.config import get_settings
from app.db.models.stored_file import DerivedSource, StoredFile
from app.schemas.sources import RecordRef, SourceRef

logger = logging.getLogger(__name__)

ACCEL_PREFIX = "/_files/"
MANIFEST_NAME = ".manifest.json"
TREE_CONTENT_TYPE = "inode/directory"
TMP_PREFIX = ".tmp-"
OCTET_STREAM = "application/octet-stream"
CACHE_CONTROL = "private, no-cache"
CSP = "default-src 'none'; sandbox"
# A row-less entry or a deleted Campaign's directory younger than this may
# belong to a put whose transaction has not committed yet: never swept.
GC_GRACE = timedelta(hours=24)

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KIND = r"[a-z0-9][a-z0-9_-]{0,63}"
_UUID_RE = re.compile(rf"^{_UUID}$")
_KIND_RE = re.compile(rf"^{_KIND}$")
_KEY_RE = re.compile(rf"^{_UUID}/{_KIND}/{_UUID}$")
# A tree path segment: never starts with "." (so never "..", never the manifest).
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_MAX_SUBPATH_LEN = 512
_MAX_SUBPATH_DEPTH = 8
_CONTENT_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

# Types a browser may execute or render as a document.
_ACTIVE_TYPES = frozenset({
    "text/html", "application/xhtml+xml", "image/svg+xml", "application/xml", "text/xml",
    "application/javascript", "text/javascript", "application/ecmascript", "text/ecmascript",
    "application/x-javascript", "text/jscript", "text/x-javascript",
})
_ACTIVE_EXTENSIONS = frozenset({".html", ".htm", ".xhtml", ".xht", ".svg", ".svgz", ".xml", ".js", ".mjs", ".cjs"})
# Served inline: audio, raster images and plain text. Everything else (PDF
# included: Chromium will not render a PDF under `CSP: sandbox`) is an attachment.
_INLINE_TYPES = frozenset({
    "text/plain", "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif",
    "image/bmp",
})
# Content types of tree entries, by extension (anything else: octet-stream).
_TREE_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".gif": "image/gif", ".avif": "image/avif", ".json": "application/json", ".txt": "text/plain",
    ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".wav": "audio/wav", ".m4a": "audio/mp4", ".webm": "audio/webm",
}


class UnsafePath(ValueError):
    """A storage key or subpath that fails validation."""


# ── Paths ──────────────────────────────────────────────────────────────────

def files_root() -> Path:
    return Path(get_settings().files_root)


def _check_under_root(path: Path) -> None:
    root = os.path.realpath(files_root())
    real = os.path.realpath(path)
    if real != root and not real.startswith(root + os.sep):
        raise UnsafePath("path leaves files_root")


def _plain(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise UnsafePath(f"{what} must be a non-empty str")
    if "\x00" in value or "\\" in value or value.startswith("/") or ".." in value.split("/"):
        raise UnsafePath(f"{what} has a NUL, a backslash, an absolute path or a `..` segment")
    return value


def key_path(storage_key: str) -> Path:
    """The path of a validated `{campaign_id}/{kind}/{uuid}` key under files_root."""
    key = _plain(storage_key, "storage_key")
    if not _KEY_RE.fullmatch(key):
        raise UnsafePath("storage_key is not {campaign_id}/{kind}/{uuid}")
    path = files_root() / key
    _check_under_root(path)
    return path


def check_subpath(subpath: Any) -> str:
    """A validated tree subpath (`z/0/0.jpg`): 1 to 8 segments of
    [A-Za-z0-9_][A-Za-z0-9_.-]*, so no `..`, no dot-file, no empty segment."""
    sub = _plain(subpath, "subpath")
    if len(sub) > _MAX_SUBPATH_LEN:
        raise UnsafePath("subpath is too long")
    parts = sub.split("/")
    if len(parts) > _MAX_SUBPATH_DEPTH or not all(_SEGMENT_RE.fullmatch(p) for p in parts):
        raise UnsafePath("subpath has an invalid segment")
    return sub


def _check_kind(kind: Any) -> str:
    if not isinstance(kind, str) or not _KIND_RE.fullmatch(kind):
        raise ValueError(f"file kind must match {_KIND}, got {kind!r}")
    return kind


def new_storage_key(campaign_id: uuid.UUID, kind: str) -> str:
    return f"{campaign_id}/{_check_kind(kind)}/{uuid.uuid4()}"


# ── Content types ──────────────────────────────────────────────────────────

def _base_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def is_active_type(content_type: str) -> bool:
    """HTML, SVG, XML, XHTML or JavaScript (any `+xml`, any `html`/`script`)."""
    base = _base_type(content_type)
    return (base in _ACTIVE_TYPES or base.endswith("+xml") or base.endswith("/xml") or "html" in base
            or "javascript" in base or "ecmascript" in base)


def check_content_type(content_type: Any) -> str:
    """The stored form (the bare `type/subtype`, lower case) of an allowed
    content type; ValueError for a malformed or active one."""
    if not isinstance(content_type, str):
        raise ValueError("content_type must be a str")
    base = _base_type(content_type)
    if not _CONTENT_TYPE_RE.fullmatch(base):
        raise ValueError(f"content_type {content_type!r} is not type/subtype")
    if is_active_type(base):
        raise ValueError(f"content_type {base!r} is refused: HTML, SVG, XML, XHTML and JS are never stored")
    if base == TREE_CONTENT_TYPE:
        raise ValueError(f"content_type {TREE_CONTENT_TYPE!r} is reserved for put_tree")
    return base


def served_content_type(content_type: str) -> str:
    """What a response says: the type, unless it is malformed or active."""
    base = _base_type(content_type or "")
    if not _CONTENT_TYPE_RE.fullmatch(base) or is_active_type(base) or base == TREE_CONTENT_TYPE:
        return OCTET_STREAM
    return base


_FILENAME_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]")


def download_name(file: StoredFile, content_type: str, subpath: str | None = None) -> str:
    """`<kind>-<file id><ext>` (ext guessed from the served type), or a tree
    entry's own name; only [A-Za-z0-9._-] characters."""
    if subpath is not None:
        name = subpath.rsplit("/", 1)[-1]
    else:
        ext = mimetypes.guess_extension(_base_type(content_type), strict=False) or ""
        name = f"{file.kind}-{file.id}{ext}"
    return _FILENAME_UNSAFE_RE.sub("_", name) or "file"


def disposition(content_type: str, filename: str | None = None) -> str:
    base = _base_type(content_type)
    value = "inline" if base.startswith("audio/") or base in _INLINE_TYPES else "attachment"
    if filename is not None:
        value += f'; filename="{_FILENAME_UNSAFE_RE.sub("_", filename)}"'
    return value


def tree_content_type(subpath: str) -> str:
    return _TREE_TYPES.get(os.path.splitext(subpath)[1].lower(), OCTET_STREAM)


def _tree_path_is_active(subpath: str) -> bool:
    ext = os.path.splitext(subpath)[1].lower()
    guessed, _ = mimetypes.guess_type(subpath, strict=False)
    return ext in _ACTIVE_EXTENSIONS or (guessed is not None and is_active_type(guessed))


# ── Session hooks: bytes follow the transaction ────────────────────────────

_PUT_KEY = "lorekeeper.files.put"        # written; unlink unless the root commits
_DELETE_KEY = "lorekeeper.files.delete"  # rows deleted; unlink once the root commits


@dataclass(frozen=True)
class _Pending:
    path: Path
    transaction: SessionTransaction | None


def _record(session: Session, key: str, path: Path) -> None:
    txn = session.get_nested_transaction() or session.get_transaction()
    session.info.setdefault(key, []).append(_Pending(path, txn))


def _within(txn: SessionTransaction | None, ancestor: SessionTransaction) -> bool:
    while txn is not None:
        if txn is ancestor:
            return True
        txn = txn.parent
    return False


def _remove(path: Path) -> None:
    """Unlink a file, symlink or tree. Never raises (logged)."""
    try:
        if path.is_symlink() or path.is_file():
            path.unlink(missing_ok=True)
        elif path.is_dir():
            shutil.rmtree(path)
    except OSError:
        logger.warning(json.dumps({"event": "file_unlink_failed", "path": str(path)}), exc_info=True)


def _remove_all(pending: list[_Pending] | None) -> None:
    for p in pending or ():
        _remove(p.path)


@event.listens_for(Session, "after_soft_rollback")
def _files_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:
        _remove_all(session.info.pop(_PUT_KEY, None))
        session.info.pop(_DELETE_KEY, None)
        return
    for key, unlink in ((_PUT_KEY, True), (_DELETE_KEY, False)):
        pending = session.info.get(key)
        if not pending:
            continue
        gone = [p for p in pending if _within(p.transaction, previous_transaction)]
        session.info[key] = [p for p in pending if not _within(p.transaction, previous_transaction)]
        if unlink:
            _remove_all(gone)


@event.listens_for(Session, "after_commit")
def _files_committed(session: Session) -> None:
    if session.in_nested_transaction():
        return  # a savepoint release: not durable yet
    session.info.pop(_PUT_KEY, None)  # the rows are durable: keep the bytes
    _remove_all(session.info.pop(_DELETE_KEY, None))


@event.listens_for(Session, "after_transaction_end")
def _files_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    # after_commit has already taken what it keeps; a root transaction that
    # ends any other way (close() without commit) leaves no stray bytes.
    if transaction.parent is None:
        _remove_all(session.info.pop(_PUT_KEY, None))
        session.info.pop(_DELETE_KEY, None)


# ── Writing ────────────────────────────────────────────────────────────────

def _check_writer(ctx: Any, campaign_id: uuid.UUID) -> None:
    if (not isinstance(ctx, CampaignContext) or ctx.read_only or ctx.user_id is None
            or ctx.campaign_id != campaign_id):
        not_found()


def _as_uuid(value: Any, what: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError(f"{what} must be a UUID, got {value!r}") from None


def _short_str(value: Any, what: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{what} must be a non-empty str of at most {limit} chars, got {value!r}")
    return value


def _source_triples(sources: Iterable[Any] | None) -> list[tuple[str, uuid.UUID, str | None]]:
    """(ref_kind, ref_id, ref_field) per source, in order, duplicates dropped.
    A source is a SourceRef, a RecordRef, a mapping with ref_kind/ref_id
    (or kind/id) and an optional ref_field/field, or such a tuple."""
    if sources is None:
        return []
    if isinstance(sources, (str, bytes, Mapping)) or not isinstance(sources, Iterable):
        raise TypeError("sources must be a list of refs")
    out: list[tuple[str, uuid.UUID, str | None]] = []
    for s in sources:
        if isinstance(s, SourceRef):
            kind, ref_id, field = s.kind.value, s.id, s.field
        elif isinstance(s, RecordRef):
            kind, ref_id, field = s.kind, s.id, s.field
        elif isinstance(s, Mapping):
            kind = s.get("ref_kind", s.get("kind"))
            ref_id = s.get("ref_id", s.get("id"))
            field = s.get("ref_field", s.get("field"))
        elif isinstance(s, tuple) and len(s) in (2, 3):
            kind, ref_id, field = s[0], s[1], s[2] if len(s) == 3 else None
        else:
            raise TypeError(f"a source must be a SourceRef, RecordRef, mapping or tuple, got {s!r}")
        triple = (_short_str(str(kind) if kind is not None else None, "ref_kind", 64),
                  _as_uuid(ref_id, "ref_id"),
                  None if field is None else _short_str(field, "ref_field", 64))
        if triple not in out:
            out.append(triple)
    return out


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _check_under_root(path.parent)
    tmp = path.parent / f"{TMP_PREFIX}{uuid.uuid4()}"
    try:
        with io.open(tmp, "xb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.rename(tmp, path)
    except BaseException:
        _remove(tmp)
        raise


def _write_tree(path: Path, entries: list[tuple[str, bytes]], manifest: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _check_under_root(path.parent)
    tmp = path.parent / f"{TMP_PREFIX}{uuid.uuid4()}"
    try:
        tmp.mkdir()
        for sub, data in entries + [(MANIFEST_NAME, manifest)]:
            target = tmp / sub
            target.parent.mkdir(parents=True, exist_ok=True)
            with io.open(target, "xb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        os.rename(tmp, path)  # the tree appears only by rename
    except BaseException:
        _remove(tmp)
        raise


def _owner_for(ctx: CampaignContext, audience_owner_id: Any) -> uuid.UUID | None:
    """The file's `audience_owner_id`: as given for a GM; for anyone else it
    must be None or the ctx's own user, and is always that user (a Player's
    file is theirs, and can never supersede a GM's or another Player's)."""
    owner_id = None if audience_owner_id is None else _as_uuid(audience_owner_id, "audience_owner_id")
    if ctx.role == GM:
        return owner_id
    if owner_id is not None and owner_id != ctx.user_id:
        raise ValueError("audience_owner_id: a non-GM ctx may only store its own files")
    return ctx.user_id


async def _insert(db: AsyncSession, ctx: CampaignContext, campaign_id: uuid.UUID, kind: str, key: str,
                  content_type: str, size: int, sha: str, cache_key: str | None,
                  sources: list[tuple[str, uuid.UUID, str | None]], audience_owner_id: uuid.UUID | None) -> StoredFile:
    if cache_key is not None and audience_owner_id is not None:
        # An owned file's cache_key is namespaced by its owner: the unique
        # index (campaign, kind, cache_key) among fresh files has no owner
        # column, and one owner's key must never collide with another's.
        cache_key = _short_str(f"{audience_owner_id}:{cache_key}", "cache_key (with its owner)", 128)
    if cache_key is not None:
        # The fresh holder of this cache_key with the same owner is superseded
        # (files.gc removes it); another owner's file is never touched.
        await db.execute(
            sa.update(StoredFile)
            .where(StoredFile.campaign_id == campaign_id, StoredFile.kind == kind,
                   StoredFile.cache_key == cache_key, sa.not_(StoredFile.stale),
                   StoredFile.audience_owner_id.is_not_distinct_from(audience_owner_id))
            .values(stale=True)
        )
    row = StoredFile(id=uuid.uuid4(), campaign_id=campaign_id, kind=kind, storage_key=key, content_type=content_type,
                     size=size, sha256=sha, audience_owner_id=audience_owner_id, cache_key=cache_key, stale=False,
                     created_by=ctx.user_id)
    db.add(row)
    for ref_kind, ref_id, ref_field in sources:
        db.add(DerivedSource(derived_type=kind, derived_id=row.id, ref_kind=ref_kind, ref_id=ref_id,
                             ref_field=ref_field))
    await db.flush()
    return row


async def _store(db: AsyncSession, path: Path, write: Any, insert: Any) -> StoredFile:
    await asyncio.to_thread(write)
    try:
        row = await insert()
    except BaseException:
        _remove(path)
        raise
    _record(db.sync_session, _PUT_KEY, path)
    return row


async def put(db: AsyncSession, ctx: CampaignContext, campaign_id: uuid.UUID | str, kind: str, data: bytes,
              content_type: str, *, cache_key: str | None = None, sources: Iterable[Any] = (),
              audience_owner_id: uuid.UUID | None = None) -> StoredFile:
    """Store `data` as a new file of `kind` in `campaign_id` (ctx's Campaign,
    a writable user ctx; else `not_found()`) and return its row, flushed but
    not committed. `sources` become its `derived_sources` (none: GM only).
    ValueError for a refused content type, a bad kind or a bad source."""
    cid = _as_uuid(campaign_id, "campaign_id")
    _check_writer(ctx, cid)
    kind = _check_kind(kind)
    ctype = check_content_type(content_type)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("put: data must be bytes")
    data = bytes(data)
    triples = _source_triples(sources)
    cache_key = None if cache_key is None else _short_str(cache_key, "cache_key", 128)
    owner_id = _owner_for(ctx, audience_owner_id)
    key = new_storage_key(cid, kind)
    path = key_path(key)
    sha = hashlib.sha256(data).hexdigest()
    return await _store(
        db, path, lambda: _write_file(path, data),
        lambda: _insert(db, ctx, cid, kind, key, ctype, len(data), sha, cache_key, triples, owner_id),
    )


def manifest_bytes(entries: Iterable[tuple[str, int, str]]) -> bytes:
    """The canonical manifest: `{"files": [[path, size, sha256], ...]}`, sorted."""
    files = sorted([list(e) for e in entries], key=lambda e: e[0])
    return json.dumps({"files": files}, sort_keys=True, separators=(",", ":")).encode()


def _tree_entries(files: Iterable[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    if isinstance(files, (str, bytes, Mapping)) or not isinstance(files, Iterable):
        raise TypeError("put_tree: files must be (path, bytes) pairs")
    out: dict[str, bytes] = {}
    for item in files:
        if not (isinstance(item, tuple) and len(item) == 2):
            raise TypeError(f"put_tree: expected (path, bytes) pairs, got {item!r}")
        sub, data = item
        try:
            sub = check_subpath(sub)
        except UnsafePath as exc:
            raise ValueError(f"put_tree: bad path {sub!r}: {exc}") from None
        if _tree_path_is_active(sub):
            raise ValueError(f"put_tree: {sub!r} would be HTML, SVG, XML, XHTML or JS")
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError(f"put_tree: {sub!r} data must be bytes")
        if sub in out:
            raise ValueError(f"put_tree: {sub!r} is listed twice")
        out[sub] = bytes(data)
    if not out:
        raise ValueError("put_tree: a tree needs at least one file")
    names = set(out)
    for sub in names:
        parts = sub.split("/")
        for i in range(1, len(parts)):
            if "/".join(parts[:i]) in names:
                raise ValueError(f"put_tree: {'/'.join(parts[:i])!r} is both a file and a directory")
    return sorted(out.items())


async def put_tree(db: AsyncSession, ctx: CampaignContext, kind: str, files: Iterable[tuple[str, bytes]],
                   sources: Iterable[Any] = (), *, cache_key: str | None = None,
                   audience_owner_id: uuid.UUID | None = None) -> StoredFile:
    """Store a tree of files (`[("z/0/0.jpg", bytes), ...]`) as one directory
    `{campaign_id}/{kind}/{uuid}/` in ctx's Campaign and one row: `size` is
    the total of the files, `sha256` the hash of the manifest
    (`.manifest.json`, `manifest_bytes`), `content_type` TREE_CONTENT_TYPE.
    Built under a temporary name and renamed into place. Serve one entry with
    `accel_response(row, subpath)`."""
    if not isinstance(ctx, CampaignContext):
        not_found()
    cid = ctx.campaign_id
    _check_writer(ctx, cid)
    kind = _check_kind(kind)
    entries = _tree_entries(files)
    triples = _source_triples(sources)
    cache_key = None if cache_key is None else _short_str(cache_key, "cache_key", 128)
    owner_id = _owner_for(ctx, audience_owner_id)
    manifest = manifest_bytes((sub, len(data), hashlib.sha256(data).hexdigest()) for sub, data in entries)
    total = sum(len(data) for _sub, data in entries)
    key = new_storage_key(cid, kind)
    path = key_path(key)
    sha = hashlib.sha256(manifest).hexdigest()
    return await _store(
        db, path, lambda: _write_tree(path, entries, manifest),
        lambda: _insert(db, ctx, cid, kind, key, TREE_CONTENT_TYPE, total, sha, cache_key, triples, owner_id),
    )


# ── Reading ────────────────────────────────────────────────────────────────

_MANIFEST_CACHE: dict[tuple[str, str], dict[str, tuple[int, str]]] = {}
_MANIFEST_CACHE_MAX = 512


def is_tree(file: StoredFile) -> bool:
    return file.content_type == TREE_CONTENT_TYPE


def read_manifest(file: StoredFile) -> dict[str, tuple[int, str]] | None:
    """{subpath: (size, sha256)} of a tree, or None when the manifest is
    missing, unreadable or does not hash to the row's `sha256`. Cached by
    (storage_key, sha256)."""
    cache_key = (file.storage_key, file.sha256)
    cached = _MANIFEST_CACHE.get(cache_key)
    if cached is not None:
        return cached
    try:
        raw = (key_path(file.storage_key) / MANIFEST_NAME).read_bytes()
    except (OSError, UnsafePath):
        return None
    if hashlib.sha256(raw).hexdigest() != file.sha256:
        return None
    try:
        listed = json.loads(raw)["files"]
        out = {}
        for sub, size, sha in listed:
            if check_subpath(sub) != sub or not isinstance(size, int) or not _SHA_RE.fullmatch(str(sha)):
                return None
            out[sub] = (size, sha)
    except (ValueError, KeyError, TypeError):
        return None
    if len(_MANIFEST_CACHE) >= _MANIFEST_CACHE_MAX:
        _MANIFEST_CACHE.clear()
    _MANIFEST_CACHE[cache_key] = out
    return out


@dataclass(frozen=True)
class Target:
    """One servable file: its path, the accel URI, its type and its hash."""
    path: Path
    accel: str
    content_type: str
    sha256: str


def resolve(file: StoredFile, subpath: str | None = None) -> Target:
    """The file (or one entry of a tree) to serve, after every check; else
    `not_found()`: a bad key or subpath, a subpath on a plain file, no subpath
    on a tree, a path not in the manifest, or bytes that are not there."""
    try:
        base = key_path(file.storage_key)
        if is_tree(file):
            if subpath is None:
                not_found()
            sub = check_subpath(subpath)
            manifest = read_manifest(file)
            entry = manifest.get(sub) if manifest is not None else None
            if entry is None:
                not_found()
            path = base / sub
            _check_under_root(path)
            accel, ctype, sha = f"{ACCEL_PREFIX}{file.storage_key}/{sub}", tree_content_type(sub), entry[1]
        else:
            if subpath is not None:
                not_found()
            path, accel, ctype, sha = base, f"{ACCEL_PREFIX}{file.storage_key}", file.content_type, file.sha256
    except UnsafePath:
        not_found()
    if path.is_symlink() or not path.is_file():
        not_found()
    return Target(path, accel, served_content_type(ctype), sha)


def _present(file: StoredFile) -> bool:
    try:
        if is_tree(file):
            base = key_path(file.storage_key)
            return base.is_dir() and not base.is_symlink() and read_manifest(file) is not None
        resolve(file)
        return True
    except (NotFound, UnsafePath):
        return False


async def open(db: AsyncSession, ctx: CampaignContext, file_id: Any) -> StoredFile:  # noqa: A001
    """The file `file_id` if ctx may read it (app/access/files.py
    `visible_file`: SQL and Python) and its bytes are on the volume; else the
    one `not_found()`."""
    row = await visible_file(db, ctx, file_id)
    if not await asyncio.to_thread(_present, row):
        not_found()
    return row


async def read_bytes(db: AsyncSession, ctx: CampaignContext, file_id: Any, subpath: str | None = None) -> bytes:
    """The bytes of a file ctx may read (or of one entry of a tree), checked
    against their sha256; else `not_found()`."""
    row = await open(db, ctx, file_id)
    target = await asyncio.to_thread(resolve, row, subpath)
    data = await asyncio.to_thread(target.path.read_bytes)
    if hashlib.sha256(data).hexdigest() != target.sha256:
        logger.warning(json.dumps({"event": "file_hash_mismatch", "file_id": str(row.id)}))
        not_found()
    return data


# ── Serving ────────────────────────────────────────────────────────────────

def etag(sha256: str, access_epoch: int) -> str:
    """`"<sha256[:32]>-e<access_epoch>"`: a grant change (new epoch) never
    revalidates against a body cached under the old one."""
    return f'"{sha256[:32]}-e{int(access_epoch)}"'


def not_modified(request: Request | None, tag: str) -> bool:
    """True when the request's If-None-Match names `tag` (or is `*`)."""
    if request is None:
        return False
    header = request.headers.get("if-none-match")
    if not header:
        return False
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:]
        if candidate == "*" or candidate == tag:
            return True
    return False


def accel_response(file: StoredFile, subpath: str | None = None, *, access_epoch: int = 0,
                   request: Request | None = None) -> Response:
    """The empty-bodied response nginx turns into the bytes: `X-Accel-Redirect:
    /_files/<storage_key>[/<subpath>]`, the content type (octet-stream for an
    active one), `Content-Disposition` (inline only for audio, raster images
    and plain text; with a filename), `Cache-Control: private, no-cache`, the epoch ETag,
    `nosniff` and a sandboxing CSP. A matching If-None-Match gets 304 with no
    accel header. Anything that cannot be served is `not_found()`."""
    target = resolve(file, subpath)
    tag = etag(target.sha256, access_epoch)
    if not_modified(request, tag):
        return Response(status_code=304, headers={"ETag": tag, "Cache-Control": CACHE_CONTROL})
    return Response(status_code=200, content=b"", headers={
        "X-Accel-Redirect": target.accel,
        "Content-Type": target.content_type,
        "Content-Disposition": disposition(target.content_type,
                                           download_name(file, target.content_type, subpath)),
        "Cache-Control": CACHE_CONTROL,
        "ETag": tag,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": CSP,
    })


# ── Deleting ───────────────────────────────────────────────────────────────

async def delete(db: AsyncSession, ctx: CampaignContext, file: StoredFile) -> None:
    """Delete `file`'s `derived_sources` rows and its row in the caller's
    transaction; its bytes (a tree recursively) are unlinked once the root
    transaction commits. A writable GM ctx of the file's Campaign only (else
    `not_found()`)."""
    if (not isinstance(ctx, CampaignContext) or ctx.role != GM or ctx.read_only or ctx.user_id is None
            or file.campaign_id != ctx.campaign_id):
        not_found()
    path = key_path(file.storage_key)
    await db.execute(sa.delete(DerivedSource).where(DerivedSource.derived_type == file.kind,
                                                    DerivedSource.derived_id == file.id))
    await db.execute(sa.delete(StoredFile).where(StoredFile.id == file.id))
    await db.flush()
    _record(db.sync_session, _DELETE_KEY, path)


# ── The stale marker ───────────────────────────────────────────────────────

async def mark_files_stale(db: AsyncSession, ref: Any) -> int:
    """Stale marker (`register_stale_marker`): every non-stale file deriving
    from the ref's row goes stale in the caller's transaction. Matches on the
    id only (a Visibility kind may differ from the stored ref_kind). Returns
    how many files it marked."""
    try:
        ref_id = _as_uuid(getattr(ref, "id", None), "ref.id")
    except ValueError:
        return 0
    ids = await files_derived_from(db, ref_id)
    if ids:
        await db.execute(sa.update(StoredFile).where(StoredFile.id.in_(ids), sa.not_(StoredFile.stale))
                         .values(stale=True))
    return len(ids)


register_stale_marker(mark_files_stale)


# ── GC (the files.gc Job, app/jobs/files_gc.py) ────────────────────────────

SUPERSEDED, ORPHAN, CAMPAIGN_DIR = "superseded", "orphan", "campaign_dir"


@dataclass(frozen=True)
class GcCandidate:
    """One thing `files.gc` removes. `key` orders the walk (the cursor)."""
    key: str
    action: str
    target: str


def campaign_dirs() -> list[uuid.UUID]:
    """The Campaign directories under files_root (UUID-named, not symlinks)."""
    root = files_root()
    if not root.is_dir():
        return []
    out = []
    with os.scandir(root) as it:
        for entry in it:
            if _UUID_RE.fullmatch(entry.name) and entry.is_dir(follow_symlinks=False):
                out.append(uuid.UUID(entry.name))
    return sorted(out)


def _old(entry: os.DirEntry, cutoff: float) -> bool:
    try:
        return entry.stat(follow_symlinks=False).st_mtime < cutoff
    except OSError:
        return False


def _scan(campaign_id: uuid.UUID, live: set[str], cutoff: float) -> tuple[list[str], list[str]]:
    """(deleted Campaigns' directories, entries of this Campaign's kind
    directories), both older than `cutoff`."""
    root = files_root()
    dead: list[str] = []
    entries: list[str] = []
    if not root.is_dir():
        return dead, entries
    with os.scandir(root) as it:
        for entry in it:
            if (_UUID_RE.fullmatch(entry.name) and entry.name not in live and entry.is_dir(follow_symlinks=False)
                    and _old(entry, cutoff)):
                dead.append(entry.name)
    cdir = root / str(campaign_id)
    if cdir.is_symlink() or not cdir.is_dir():
        return dead, entries
    with os.scandir(cdir) as kinds:
        for kind in kinds:
            # Files here (the `.backup-live-audio` opt-in marker) are not entries.
            if not _KIND_RE.fullmatch(kind.name) or not kind.is_dir(follow_symlinks=False):
                continue
            with os.scandir(kind.path) as items:
                for item in items:
                    if _old(item, cutoff):
                        entries.append(f"{campaign_id}/{kind.name}/{item.name}")
    return dead, entries


def _entry_path(rel: str) -> Path:
    """The path of `{campaign_id}/{kind}/{name}` (any name: row-less entries
    include temporary ones), its parent checked under files_root."""
    parts = rel.split("/")
    if (len(parts) != 3 or not _UUID_RE.fullmatch(parts[0]) or not _KIND_RE.fullmatch(parts[1])
            or parts[2] in ("", ".", "..") or any(c in parts[2] for c in "\\\x00")):
        raise UnsafePath(f"not a Campaign entry: {rel!r}")
    path = files_root() / rel
    _check_under_root(path.parent)
    return path


def _campaign_dir_path(cid: str) -> Path:
    if not _UUID_RE.fullmatch(cid):
        raise UnsafePath(f"not a Campaign directory: {cid!r}")
    path = files_root() / cid
    _check_under_root(path)
    return path


def _superseded(rows: list[StoredFile]) -> list[StoredFile]:
    fresh = {(r.kind, r.cache_key, r.audience_owner_id) for r in rows if not r.stale and r.cache_key is not None}
    return [r for r in rows if r.stale and r.cache_key is not None
            and (r.kind, r.cache_key, r.audience_owner_id) in fresh]


async def gc_candidates(db: AsyncSession, ctx: CampaignContext, *, now: datetime | None = None) -> list[GcCandidate]:
    """Everything `files.gc` would remove for ctx's Campaign now, ordered by
    key: deleted Campaigns' directories, row-less entries, superseded files.
    A writable GM ctx only (`campaign_files`)."""
    rows = await campaign_files(db, ctx)
    cutoff = ((now or datetime.now(timezone.utc)) - GC_GRACE).timestamp()
    live = {str(cid) for cid in await campaign_owners(db, created_before=None)}
    dead, entries = await asyncio.to_thread(_scan, ctx.campaign_id, live, cutoff)
    keys = {r.storage_key for r in rows}
    out = [GcCandidate(f"1:{cid}", CAMPAIGN_DIR, cid) for cid in dead]
    out += [GcCandidate(f"2:{rel}", ORPHAN, rel) for rel in entries if rel not in keys]
    out += [GcCandidate(f"3:{r.id}", SUPERSEDED, str(r.id)) for r in _superseded(rows)]
    return sorted(out, key=lambda c: c.key)


async def gc_one(db: AsyncSession, ctx: CampaignContext, item: GcCandidate, *, now: datetime | None = None) -> bool:
    """Remove one candidate if it still qualifies; True when it did. A
    superseded file goes through `delete` (bytes after the commit); a
    row-less entry or a deleted Campaign's directory is removed at once."""
    cutoff = ((now or datetime.now(timezone.utc)) - GC_GRACE).timestamp()
    if item.action == SUPERSEDED:
        rows = await campaign_files(db, ctx)
        row = next((r for r in _superseded(rows) if str(r.id) == item.target), None)
        if row is None:
            return False
        await delete(db, ctx, row)
        return True
    if item.action == ORPHAN:
        try:
            path = _entry_path(item.target)
        except UnsafePath:
            return False  # a name we would never write: left alone, never fails the Job
        if not item.target.startswith(f"{ctx.campaign_id}/"):
            return False
        if item.target in {r.storage_key for r in await campaign_files(db, ctx)}:
            return False
        try:
            if os.lstat(path).st_mtime >= cutoff:
                return False
        except OSError:
            return False
        await asyncio.to_thread(_remove, path)
        return True
    if item.action == CAMPAIGN_DIR:
        try:
            path = _campaign_dir_path(item.target)
        except UnsafePath:
            return False
        if item.target in {str(cid) for cid in await campaign_owners(db, created_before=None)}:
            return False
        if path.is_symlink() or not path.is_dir():
            return False
        await asyncio.to_thread(_remove, path)
        return True
    raise ValueError(f"gc_one: unknown action {item.action!r}")


__all__ = [
    "ACCEL_PREFIX", "GC_GRACE", "MANIFEST_NAME", "TREE_CONTENT_TYPE", "GcCandidate", "Target", "UnsafePath",
    "accel_response", "campaign_dirs", "check_content_type", "check_subpath", "delete", "etag", "files_root",
    "gc_candidates", "gc_one", "is_active_type", "key_path", "manifest_bytes", "mark_files_stale", "not_modified",
    "open", "put", "put_tree", "read_bytes", "read_manifest", "resolve",
]
