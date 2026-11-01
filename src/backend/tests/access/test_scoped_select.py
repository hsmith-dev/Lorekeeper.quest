"""E0-Access.3: scoped_select / scoped_get / scoped_select_multi with the EV-4
actors and canaries, the audience_ctx matrix on real ctxs, and the
`X-Lorekeeper-Preview: member` header.

Each registered model is read through `scoped_select` for each actor's ctx
in Campaign A; every returned row's column values (except the model's
`gm_fields`, which E0-Access.4's `project` drops) are scanned for canaries,
and every token found must be one the actor may see (`Actor.may_see`: GM of
the token's Campaign). GM and Co-GM must find every GM-only canary.
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import date

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.access import (
    ANON_VIEW, MEMBER_VIEW, MEMBERS, PREVIEW_HEADER, PUBLIC, REGISTRY, CampaignContext, NotFound, as_user,
    audience_ctx, ctx_for, gm_fields, require_campaign, require_campaign_for, role_map, scoped_get, scoped_select,
    scoped_select_multi,
)
from app.db.models import (
    CharacterSheet, ChatSession, JournalEntry, SessionPlan, ShorthandTerm, SourceChunk, SourceDocument,
    TagCategory,
)
from app.access.registry import AlwaysGM, scope_column
from app.db.session import get_db
from tests.ev4.fixtures import ev4, find_canaries, mint_canary  # noqa: F401  (ev4 registers the fixture)

NOT_FOUND = {"detail": "Not found"}
# The global always_gm models (derived_sources, data_backfills) have no
# Campaign scope; scoped_select refuses them (tests/access/test_audience.py).
CAMPAIGN_MODELS = [m for m in REGISTRY if not (
    scope_column(m) is None and isinstance(REGISTRY[m], AlwaysGM))]
RANDOM = uuid.UUID("00000000-0000-4000-8000-000000000000")

# The text column each stored model's extra rows carry their token in.
TEXT_COLUMN = {
    JournalEntry: "narrative", CharacterSheet: "name", SessionPlan: "title", SourceDocument: "title",
    ShorthandTerm: "term", TagCategory: "name", ChatSession: "title",
}
# Seed canaries that live only in gm_fields (never scanned).
GM_FIELD_KINDS = {"SHORTHAND", "NPCNOTES", "QUESTNOTES"}


def _row_text(model, row) -> str:
    skip = set(gm_fields(model))
    values = {c.key: getattr(row, c.key) for c in sa.inspect(model).column_attrs if c.key not in skip}
    return json.dumps(values, default=str)


@dataclasses.dataclass
class Extra:
    """Extra rows in Campaign A: GM-only canaries and plain visible markers."""

    canaries: set[str]
    party: set[str]            # visible to every Member and anon
    party_player_kind: set[str]  # party, kind=player: Members, not anon
    player_private: set[str]   # Private to the `player` actor


def _marker(kind: str) -> str:
    return f"MARK-{kind}-{uuid.uuid4().hex}"


async def _add_extras(db, ev4) -> Extra:
    a = ev4.a.campaign_id
    gm_id = ev4.a.owner_id
    player = await ev4.actor("player")
    template_id = ev4.a.ids["character_sheet_templates"][0]
    extra = Extra(set(), set(), set(), set())

    def make(model, text: str, author, visibility=None, **kw):
        col = TEXT_COLUMN[model]
        base = {col: text}
        if model is JournalEntry:
            base.update(user_id=author, campaign_id=a, shorthand="s", narrative=text, entry_hash=uuid.uuid4().hex,
                        session_date=date(2026, 2, 1))
        elif model is CharacterSheet:
            base.update(created_by_user_id=author, campaign_id=a, template_id=template_id, data={})
        elif model is SessionPlan:
            base.update(user_id=author, campaign_id=a, content="c")
        elif model is SourceDocument:
            base.update(user_id=author, campaign_id=a, filename="f.pdf")
        elif model is ShorthandTerm:
            base.update(user_id=author, campaign_id=a, meaning="m")
        elif model is TagCategory:
            base.update(created_by_user_id=author, campaign_id=a)
        elif model is ChatSession:
            base.update(user_id=author, campaign_id=a, messages=[], message_count=0)
        if visibility is not None:
            base["visibility"] = visibility
        base.update(kw)
        db.add(model(**base))

    for model in TEXT_COLUMN:
        if model is ChatSession:  # every chat session is Owner(author)
            token = mint_canary("XC", a).token
            extra.canaries.add(token)
            make(model, token, gm_id)
            mark = _marker("CHAT")
            extra.player_private.add(mark)
            make(model, mark, player.user_id)
            continue
        for vis in ("gm", "private"):
            # Short kinds: shorthand_terms.term and tag_categories.name are varchar(50).
            token = mint_canary(f"X{vis[0].upper()}", a).token
            extra.canaries.add(token)
            make(model, token, gm_id, vis)
        mark = _marker("PRIV")
        extra.player_private.add(mark)
        make(model, mark, player.user_id, "private")
        mark = _marker("PARTY")
        extra.party.add(mark)
        make(model, mark, gm_id, "party")
        if model is JournalEntry:
            mark = _marker("PKIND")
            extra.party_player_kind.add(mark)
            make(model, mark, player.user_id, "party", kind="player")
    await db.commit()
    return extra


@pytest_asyncio.fixture
async def scene(ev4, db):
    extra = await _add_extras(db, ev4)
    a = ev4.a.campaign_id
    gm_ctx = await ctx_for(db, ev4.a.owner_id, a)
    actors = {name: await ev4.actor(name) for name in ("gm_owner", "co_gm", "player", "player_2",
                                                        "cross_gm_player", "anon_share")}
    ctxs = {
        "gm_owner": gm_ctx,
        "co_gm": await ctx_for(db, actors["co_gm"].user_id, a),
        "player": await ctx_for(db, actors["player"].user_id, a),
        "player_2": await ctx_for(db, actors["player_2"].user_id, a),
        "cross_gm_player": await ctx_for(db, actors["cross_gm_player"].user_id, a),
        "anon_share": audience_ctx(a, ANON_VIEW, by=gm_ctx),
        "preview": audience_ctx(a, MEMBER_VIEW, by=gm_ctx),
    }
    return dataclasses.make_dataclass("Scene", ["ev4", "extra", "actors", "ctxs"])(ev4, extra, actors, ctxs)


async def _scan(db, ctx: CampaignContext) -> tuple[set[str], str]:
    tokens: set[str] = set()
    texts = []
    for model in CAMPAIGN_MODELS:
        for row in (await db.execute(scoped_select(model, ctx))).scalars().all():
            text = _row_text(model, row)
            texts.append(text)
            tokens |= set(find_canaries(text))
    return tokens, "\n".join(texts)


def _may_see(scene, name: str, token: str) -> bool:
    if name == "preview":  # the GM reading as a Member: GM-only canaries are leaks
        return False
    return scene.actors[name].may_see(token)


@pytest.mark.parametrize("name", ["gm_owner", "co_gm", "player", "player_2", "cross_gm_player", "anon_share",
                                  "preview"])
async def test_canaries_follow_may_see(db, scene, name):
    tokens, text = await _scan(db, scene.ctxs[name])
    leaks = sorted(t for t in tokens if not _may_see(scene, name, t))
    assert not leaks, f"{name} sees GM-only canaries {leaks}"
    x = scene.extra
    if name in ("gm_owner", "co_gm"):
        expected = {c.token for c in scene.ev4.a.canaries if c.kind not in GM_FIELD_KINDS} | x.canaries
        assert tokens == expected, f"{name} misses {sorted(expected - tokens)}"
        seen = x.party | x.party_player_kind | x.player_private
    elif name == "player":
        assert not tokens
        seen = x.party | x.party_player_kind | x.player_private
    elif name in ("player_2", "cross_gm_player", "preview"):
        assert not tokens
        seen = x.party | x.party_player_kind
    else:  # anon_share
        assert not tokens
        seen = x.party
    every = x.party | x.party_player_kind | x.player_private
    assert {m for m in every if m in text} == seen, name


async def test_counts_and_ordering(db, scene):
    x = scene.extra

    async def count(model, ctx):
        stmt = sa.select(sa.func.count()).select_from(scoped_select(model, ctx).subquery())
        return (await db.execute(stmt)).scalar_one()

    c = scene.ctxs
    # Seed: one gm plan; extras: gm, private-by-GM, private-by-player, party.
    assert [await count(SessionPlan, c[n]) for n in ("gm_owner", "co_gm", "player", "player_2", "preview",
                                                      "anon_share")] == [5, 5, 2, 1, 1, 1]
    # Seed: 2 party entries (kind gm); extras: gm, private-by-GM, private-by-player, party, party kind=player.
    assert [await count(JournalEntry, c[n]) for n in ("gm_owner", "player", "player_2", "preview",
                                                       "anon_share")] == [7, 5, 4, 4, 3]
    # The seeded chunk's document is gm: chunks follow their document.
    assert await count(SourceChunk, c["gm_owner"]) == 1 and await count(SourceChunk, c["player"]) == 0
    stmt = scoped_select(JournalEntry, c["player"]).order_by(JournalEntry.session_date, JournalEntry.narrative)
    rows = (await db.execute(stmt)).scalars().all()
    assert [r.session_date for r in rows] == sorted(r.session_date for r in rows)
    assert x.party_player_kind <= {r.narrative for r in rows}


async def test_scoped_get_hidden_equals_missing(db, scene):
    ev4 = scene.ev4
    player = scene.ctxs["player"]
    gm_plan = ev4.a.ids["session_plans"][0]
    with pytest.raises(NotFound) as hidden:
        await scoped_get(db, SessionPlan, player, gm_plan)
    with pytest.raises(NotFound) as missing:
        await scoped_get(db, SessionPlan, player, RANDOM)
    with pytest.raises(NotFound) as junk:
        await scoped_get(db, SessionPlan, player, "not-a-uuid")
    assert (hidden.value.status_code, hidden.value.detail) == (missing.value.status_code, missing.value.detail) \
        == (junk.value.status_code, junk.value.detail) == (404, "Not found")
    assert (await scoped_get(db, SessionPlan, scene.ctxs["co_gm"], str(gm_plan))).id == gm_plan
    # A row of another Campaign is missing even to that Campaign's GM in A.
    cross = await scene.ev4.actor("cross_gm_player")
    b_plan = ev4.b.ids["session_plans"][0]
    with pytest.raises(NotFound):
        await scoped_get(db, SessionPlan, scene.ctxs["gm_owner"], b_plan)
    b_ctx = await ctx_for(db, cross.user_id, ev4.b.campaign_id)
    assert (await scoped_get(db, SessionPlan, b_ctx, b_plan)).id == b_plan


async def test_scoped_select_multi_per_role(db, scene):
    """Owner of B, Player in A: all of B, A filtered as that Player."""
    ev4 = scene.ev4
    cross = scene.actors["cross_gm_player"]
    roles = await role_map(db, cross.user_id)
    assert roles == {ev4.a.campaign_id: "player", ev4.b.campaign_id: "gm"} and roles.user_id == cross.user_id
    for model in (SessionPlan, SourceDocument, SourceChunk, JournalEntry, ShorthandTerm, CharacterSheet,
                  ChatSession):
        rows = (await db.execute(scoped_select_multi(model, roles))).scalars().all()
        tokens = set()
        for r in rows:
            tokens |= set(find_canaries(_row_text(model, r)))
        b_tokens = {t for t in tokens if t in ev4.b.tokens}
        assert tokens == b_tokens, f"{model.__name__}: A canaries leaked {sorted(tokens - b_tokens)}"
        a_rows = [r for r in rows if r.campaign_id == ev4.a.campaign_id]
        b_rows = [r for r in rows if r.campaign_id == ev4.b.campaign_id]
        all_b = (await db.execute(sa.select(model).where(model.campaign_id == ev4.b.campaign_id))).scalars().all()
        assert {r.id for r in b_rows} == {r.id for r in all_b}, model.__name__
        as_player = (await db.execute(scoped_select(model, scene.ctxs["cross_gm_player"]))).scalars().all()
        assert {r.id for r in a_rows} == {r.id for r in as_player}, model.__name__
    assert (await db.execute(scoped_select_multi(SessionPlan, {}))).scalars().all() == []
    with pytest.raises(ValueError):  # a Player Campaign without the user to filter as
        scoped_select_multi(SessionPlan, {ev4.a.campaign_id: "player"})


async def test_scoped_select_multi_derived_matches_scoped_select_per_campaign(db, scene):
    """Player in A and C, GM of B: for a derived model (SourceChunk), each
    Campaign's rows from scoped_select_multi equal scoped_select for that
    Campaign's ctx, GM Campaigns included (parent EXISTS applied there too)."""
    from tests.ev4.fixtures import create_user, seed_canary_campaign

    ev4 = scene.ev4
    cross = scene.actors["cross_gm_player"]
    c_owner = await create_user(db, "c_owner")
    c = await seed_canary_campaign(db, c_owner)
    await ev4.make_member(role="player", campaign_id=c.campaign_id, user=await db.get(type(c_owner), cross.user_id))
    a, b = ev4.a.campaign_id, ev4.b.campaign_id

    async def doc_with_chunk(campaign_id, owner_id, visibility, chunk_campaign=None):
        doc = SourceDocument(user_id=owner_id, campaign_id=campaign_id, title="t", filename="f.pdf",
                             visibility=visibility)
        db.add(doc)
        await db.flush()
        db.add(SourceChunk(source_document_id=doc.id, user_id=owner_id, campaign_id=chunk_campaign or campaign_id,
                           chunk_index=0, content="c"))

    # A visible-parent chunk in each Player Campaign, a hidden one in A.
    await doc_with_chunk(a, ev4.a.owner_id, "party")
    await doc_with_chunk(a, ev4.a.owner_id, "gm")
    await doc_with_chunk(c.campaign_id, c_owner.id, "party")
    # A chunk filed under B whose document is in A: hidden even to B's GM by scoped_select.
    await doc_with_chunk(a, ev4.a.owner_id, "party", chunk_campaign=b)
    await db.commit()

    roles = await role_map(db, cross.user_id)
    assert roles == {a: "player", b: "gm", c.campaign_id: "player"}
    rows = (await db.execute(scoped_select_multi(SourceChunk, roles))).scalars().all()
    for cid in roles:
        per_campaign = {r.id for r in rows if r.campaign_id == cid}
        ctx = await ctx_for(db, cross.user_id, cid)
        single = {r.id for r in (await db.execute(scoped_select(SourceChunk, ctx))).scalars().all()}
        assert per_campaign == single, (cid, roles[cid])
        assert single, f"no visible chunk in {roles[cid]} Campaign {cid}"


async def test_audience_ctx_on_real_ctxs(db, scene):
    a = scene.ev4.a.campaign_id
    c = scene.ctxs
    player, player_2 = scene.actors["player"], scene.actors["player_2"]
    for target in (ANON_VIEW, MEMBER_VIEW, as_user(player.user_id), as_user(player_2.user_id)):
        assert audience_ctx(a, target, by=c["gm_owner"]).read_only
        assert audience_ctx(a, target, by=c["co_gm"]).read_only
    assert audience_ctx(a, as_user(player.user_id), by=c["player"]).audience == c["player"].audience
    with pytest.raises(NotFound):
        audience_ctx(a, as_user(player_2.user_id), by=c["player"])
    with pytest.raises(NotFound):
        audience_ctx(a, MEMBER_VIEW, by=c["anon_share"])
    with pytest.raises(NotFound):
        audience_ctx(scene.ev4.b.campaign_id, ANON_VIEW, by=c["gm_owner"])
    # as_user(player) from the GM reads exactly what the Player reads.
    via_gm = audience_ctx(a, as_user(player.user_id), by=c["gm_owner"])
    for model in CAMPAIGN_MODELS:
        got = {sa.inspect(r).identity for r in (await db.execute(scoped_select(model, via_gm))).scalars()}
        own = {sa.inspect(r).identity for r in (await db.execute(scoped_select(model, c["player"]))).scalars()}
        assert got == own, model.__name__


# ── The preview header (RC-7) ──────────────────────────────────────────────

def _ctx_json(ctx: CampaignContext) -> dict:
    return {"role": ctx.role, "is_owner": ctx.is_owner, "read_only": ctx.read_only,
            "audience": ctx.audience.level.value, "user_id": str(ctx.user_id) if ctx.user_id else None}


def _toy(db) -> FastAPI:
    toy = FastAPI()

    async def read(ctx: CampaignContext = Depends(require_campaign("player"))):
        return _ctx_json(ctx)

    async def gm_read(ctx: CampaignContext = Depends(require_campaign("gm"))):
        return _ctx_json(ctx)

    async def no_preview(ctx: CampaignContext = Depends(require_campaign("player", preview=False))):
        return _ctx_json(ctx)

    async def entry(ctx: CampaignContext = Depends(require_campaign_for(JournalEntry, "journal_id", "player"))):
        return _ctx_json(ctx)

    toy.add_api_route("/c/{campaign_id}/read", read, methods=["GET", "HEAD"])
    toy.add_api_route("/c/{campaign_id}/write", read, methods=["POST", "PUT", "PATCH", "DELETE"])
    toy.add_api_route("/c/{campaign_id}/gm", gm_read)
    toy.add_api_route("/c/{campaign_id}/raw", no_preview, methods=["GET", "POST"])
    toy.add_api_route("/journals/{journal_id}", entry)
    toy.dependency_overrides[get_db] = lambda: db
    return toy


@pytest_asyncio.fixture
async def toy(db):
    async with AsyncClient(transport=ASGITransport(app=_toy(db)), base_url="http://toy") as c:
        yield c


PREVIEW = {PREVIEW_HEADER: "member"}


async def test_preview_narrows_a_gm_to_the_member_view(toy, scene):
    a = scene.ev4.a.campaign_id
    for who in ("gm_owner", "co_gm"):
        h = scene.actors[who].headers
        plain = await toy.get(f"/c/{a}/read", headers=h)
        assert plain.json()["role"] == "gm"
        r = await toy.get(f"/c/{a}/read", headers={**h, **PREVIEW})
        assert r.status_code == 200
        assert r.json() == {"role": "player", "is_owner": False, "read_only": True,
                            "audience": MEMBERS.level.value, "user_id": None}
        # Item routes narrow too.
        entry_id = scene.ev4.a.ids["journal_entries"][0]
        r = await toy.get(f"/journals/{entry_id}", headers={**h, **PREVIEW})
        assert r.json()["audience"] == "members"
        # A gm route is out of reach in preview, like for any Player.
        missing = await toy.get(f"/c/{RANDOM}/gm", headers=h)
        r = await toy.get(f"/c/{a}/gm", headers={**h, **PREVIEW})
        assert r.status_code == 404 and r.content == missing.content and r.json() == NOT_FOUND
        # Writes in preview are 404, whatever the method.
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            r = await toy.request(method, f"/c/{a}/write", headers={**h, **PREVIEW})
            assert r.status_code == 404 and r.json() == NOT_FOUND, method
            assert (await toy.request(method, f"/c/{a}/write", headers=h)).status_code == 200, method
        assert (await toy.head(f"/c/{a}/read", headers={**h, **PREVIEW})).status_code == 200
        # preview=False opts out entirely.
        r = await toy.post(f"/c/{a}/raw", headers={**h, **PREVIEW})
        assert r.status_code == 200 and r.json()["role"] == "gm"


@pytest.mark.parametrize("value", ["Member", "MEMBER", "members", "gm", "player", "", "member "])
async def test_other_header_values_are_ignored(toy, scene, value):
    a = scene.ev4.a.campaign_id
    h = scene.actors["gm_owner"].headers
    plain = await toy.get(f"/c/{a}/read", headers=h)
    r = await toy.get(f"/c/{a}/read", headers={**h, PREVIEW_HEADER: value})
    assert r.content == plain.content


async def test_preview_never_widens(toy, client, scene):
    """A Player (and a Share Link viewer) with the header get byte-identical responses."""
    a = scene.ev4.a.campaign_id
    for who in ("player", "cross_gm_player"):
        h = scene.actors[who].headers
        for url in (f"/c/{a}/read", f"/c/{a}/gm", f"/journals/{scene.ev4.a.ids['journal_entries'][0]}"):
            plain = await toy.get(url, headers=h)
            with_header = await toy.get(url, headers={**h, **PREVIEW})
            assert (plain.status_code, plain.content) == (with_header.status_code, with_header.content), (who, url)
        plain = await toy.post(f"/c/{a}/write", headers=h)
        with_header = await toy.post(f"/c/{a}/write", headers={**h, **PREVIEW})
        assert (plain.status_code, plain.content) == (with_header.status_code, with_header.content)
        plain = await client.get(f"/api/campaigns/{a}/me", headers=h)
        with_header = await client.get(f"/api/campaigns/{a}/me", headers={**h, **PREVIEW})
        assert plain.status_code == 200 and plain.content == with_header.content
    token = scene.ev4.a.share_token
    for url in (f"/api/share/{token}", f"/api/share/{token}/journals", f"/api/share/{token}/npcs"):
        plain = await client.get(url)
        with_header = await client.get(url, headers=PREVIEW)
        assert plain.status_code == 200 and plain.content == with_header.content, url


async def test_me_reports_the_real_role_in_preview(client, scene):
    a = scene.ev4.a.campaign_id
    for who, display in (("gm_owner", "Owner"), ("co_gm", "Co-GM")):
        r = await client.get(f"/api/campaigns/{a}/me", headers={**scene.actors[who].headers, **PREVIEW})
        assert r.status_code == 200
        assert r.json() == {"campaign_id": str(a), "role": "gm", "is_owner": who == "gm_owner",
                            "display_role": display}


async def test_cors_preflight_allows_the_preview_header(client, scene):
    a = scene.ev4.a.campaign_id
    r = await client.options(f"/api/campaigns/{a}/me", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization, x-lorekeeper-preview",
    })
    assert r.status_code == 200, r.text
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-lorekeeper-preview" in allowed


def test_public_is_what_anon_reads():
    assert PUBLIC.level.value == "public"
