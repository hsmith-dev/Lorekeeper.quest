"""E0-Access.4: access.project / project_all, the Party schemas, share_ctx,
the Vary header and preview on the touched routes."""
from __future__ import annotations

import dataclasses
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.orm import selectinload

from app.access import (
    ANON_VIEW, GM_AUDIENCE, MEMBER_VIEW, PREVIEW_HEADER, PROJECTIONS, REGISTRY, CampaignContext, NotFound,
    Projection, audience_ctx, check_create, check_party_schemas, ctx_for, project, project_all,
    resolve_share_token, role_ctx, role_map, scoped_get, scoped_select, scoped_select_multi, share_ctx, stored,
)
from app.db.models import (
    Campaign, CharacterSheet, JournalEntry, JournalTag, NpcEntry, Quest, Tag, TagCategory, TagType,
)
from app.db.models.share_token import CampaignShareToken
from app.schemas.journal import JournalGMResponse, JournalPartyResponse
from app.schemas.npc import NpcGMResponse, NpcPartyResponse
from app.schemas.quest import QuestGMResponse, QuestPartyResponse
from app.schemas.share import (
    PublicCampaignResponse, PublicJournalResponse, PublicNpcResponse, PublicQuestResponse, PublicTagResponse,
)
from app.schemas.tag import TagPartyResponse
from tests.ev4.fixtures import ev4, find_canaries, mint_canary  # noqa: F401  (ev4 registers the fixture)

NOT_FOUND = {"detail": "Not found"}
RANDOM = uuid.UUID("00000000-0000-4000-8000-000000000000")
PREVIEW = {PREVIEW_HEADER: "member"}
ENTRY_TAGS = selectinload(JournalEntry.tags).selectinload(Tag.custom_category)


# ── Schemas ────────────────────────────────────────────────────────────────

def test_party_schemas_carry_no_gm_field():
    check_party_schemas()  # also runs at import
    assert "shorthand" not in JournalPartyResponse.model_fields
    assert "notes" not in NpcPartyResponse.model_fields and "notes" not in QuestPartyResponse.model_fields
    assert "shorthand" in JournalGMResponse.model_fields
    assert "notes" in NpcGMResponse.model_fields and "notes" in QuestGMResponse.model_fields
    for proj in PROJECTIONS.values():
        for schema in (proj.party, proj.anon):
            if schema is not None:
                assert "field_visibility" not in schema.model_fields
    for model in {k[0] if isinstance(k, tuple) else k for k in PROJECTIONS}:
        assert model in REGISTRY


def test_openapi_documents_the_gm_schemas_of_projected_routes():
    from app.main import app

    spec = app.openapi()
    get_entry = spec["paths"]["/api/journals/{journal_id}"]["get"]["responses"]["200"]
    assert "JournalGMResponse" in str(get_entry)
    assert "/api/campaigns/{campaign_id}" in spec["paths"]


def test_public_names_are_the_party_schemas():
    assert PublicJournalResponse is JournalPartyResponse
    assert PublicNpcResponse is NpcPartyResponse and PublicQuestResponse is QuestPartyResponse
    assert PublicTagResponse is TagPartyResponse
    assert PROJECTIONS[Campaign].anon is PublicCampaignResponse


def test_import_check_rejects_a_gm_field_in_a_party_schema():
    class LeakyParty(BaseModel):
        id: uuid.UUID
        shorthand: str

    class NestsGM(BaseModel):
        entry: JournalGMResponse

    class HasFieldVisibility(BaseModel):
        field_visibility: dict

    with pytest.raises(RuntimeError, match="shorthand"):
        check_party_schemas({JournalEntry: Projection(JournalGMResponse, LeakyParty)})
    class NpcWithNotes(BaseModel):
        id: uuid.UUID
        notes: str | None = None

    with pytest.raises(RuntimeError, match="notes"):
        check_party_schemas({NpcEntry: Projection(NpcGMResponse, NpcWithNotes)})
    with pytest.raises(RuntimeError, match="nests the GM schema"):
        check_party_schemas({**PROJECTIONS, (JournalEntry, "x"): Projection(JournalGMResponse, NestsGM)})
    with pytest.raises(RuntimeError, match="field_visibility"):
        check_party_schemas({CharacterSheet: Projection(PROJECTIONS[CharacterSheet].gm, HasFieldVisibility)})
    with pytest.raises(RuntimeError, match="is the GM schema"):
        check_party_schemas({Quest: Projection(QuestGMResponse, QuestGMResponse)})


# ── Fixtures ───────────────────────────────────────────────────────────────

@dataclasses.dataclass
class Scene:
    ev4: object
    ctxs: dict
    entry: uuid.UUID          # party entry with a manual tag, a Shorthand tag and a hidden-category tag
    gm_entry: uuid.UUID
    shorthand_tag: uuid.UUID
    manual_tag: uuid.UUID
    hidden_cat_tag: uuid.UUID
    visible_cat_tag: uuid.UUID


async def _tag(db, entry_id, source_field, *, category=None, name=None):
    tag = Tag(name=name or f"T {uuid.uuid4().hex[:10]}", tag_type=None if category else TagType.character,
              custom_category_id=category)
    db.add(tag)
    await db.flush()
    db.add(JournalTag(journal_id=entry_id, tag_id=tag.id, source_field=source_field))
    return tag.id


@pytest.fixture
async def scene(ev4, db):
    a = ev4.a.campaign_id
    owner = ev4.a.owner_id
    entry = JournalEntry(user_id=owner, campaign_id=a, shorthand=mint_canary("XSH", a).token, narrative="Party.",
                         entry_hash=uuid.uuid4().hex, session_date=date(2026, 4, 1))
    gm_entry = JournalEntry(user_id=owner, campaign_id=a, shorthand="s", narrative=mint_canary("XGM", a).token,
                            entry_hash=uuid.uuid4().hex, visibility="gm")
    hidden_cat = TagCategory(campaign_id=a, created_by_user_id=owner, name=mint_canary("XC", a).token,
                             visibility="gm")
    visible_cat = TagCategory(campaign_id=a, created_by_user_id=owner, name=f"Deity {uuid.uuid4().hex[:8]}")
    db.add_all([entry, gm_entry, hidden_cat, visible_cat])
    await db.flush()
    shorthand_tag = await _tag(db, entry.id, "shorthand", name=mint_canary("XTAG", a).token)
    manual_tag = await _tag(db, entry.id, "manual")
    hidden_cat_tag = await _tag(db, entry.id, None, category=hidden_cat.id)
    visible_cat_tag = await _tag(db, entry.id, "narrative", category=visible_cat.id)
    await db.commit()
    gm = await ctx_for(db, owner, a)
    ctxs = {"gm": gm, "co_gm": await ctx_for(db, (await ev4.actor("co_gm")).user_id, a),
            "player": await ctx_for(db, (await ev4.actor("player")).user_id, a),
            "preview": audience_ctx(a, MEMBER_VIEW, by=gm), "anon": audience_ctx(a, ANON_VIEW, by=gm)}
    return Scene(ev4, ctxs, entry.id, gm_entry.id, shorthand_tag, manual_tag, hidden_cat_tag, visible_cat_tag)


async def _load(db, ctx, entry_id):
    return await scoped_get(db, JournalEntry, ctx, entry_id, options=[ENTRY_TAGS])


# ── project ────────────────────────────────────────────────────────────────

async def test_schema_by_role_and_reference_removal(db, scene):
    for name, schema in (("gm", JournalGMResponse), ("co_gm", JournalGMResponse), ("player", JournalPartyResponse),
                         ("preview", JournalPartyResponse), ("anon", JournalPartyResponse)):
        ctx = scene.ctxs[name]
        (out,) = await project_all(db, [await _load(db, ctx, scene.entry)], ctx)
        assert type(out) is schema, name
        body = out.model_dump(mode="json")
        tags = {t["id"]: t for t in body["tags"]}
        if schema is JournalGMResponse:
            assert body["shorthand"].startswith("CANARY-XSH")
            assert set(tags) == {str(t) for t in (scene.shorthand_tag, scene.manual_tag, scene.hidden_cat_tag,
                                                  scene.visible_cat_tag)}
            assert tags[str(scene.hidden_cat_tag)]["custom_category"] is not None
        else:
            assert "shorthand" not in body
            # The Shorthand-only tag is removed; the hidden category is null; the rest is served.
            assert set(tags) == {str(t) for t in (scene.manual_tag, scene.hidden_cat_tag, scene.visible_cat_tag)}
            assert tags[str(scene.hidden_cat_tag)]["custom_category"] is None
            assert tags[str(scene.visible_cat_tag)]["custom_category"]["name"].startswith("Deity")
            assert not find_canaries(out.model_dump_json()), name


async def test_project_hidden_row_is_not_found(db, scene):
    gm_row = await db.get(JournalEntry, scene.gm_entry)
    for name in ("player", "preview", "anon"):
        with pytest.raises(NotFound):
            project(gm_row, scene.ctxs[name], links={})
    # A row of another Campaign is not found even for a GM.
    other = dataclasses.replace(scene.ctxs["gm"], campaign_id=uuid.uuid4())
    with pytest.raises(NotFound):
        project(gm_row, other)
    npc = await db.get(NpcEntry, scene.ev4.a.ids["npcs"][0])
    assert type(project(npc, scene.ctxs["gm"])) is NpcGMResponse
    for name in ("player", "preview", "anon"):
        with pytest.raises(NotFound):
            project(npc, scene.ctxs[name])


async def test_non_gm_entry_with_tags_needs_links(db, scene):
    entry = await _load(db, scene.ctxs["player"], scene.entry)
    with pytest.raises(RuntimeError, match="links"):
        project(entry, scene.ctxs["player"])
    assert project(entry, scene.ctxs["gm"]).shorthand  # a GM needs no links


async def test_project_all_with_a_role_map_uses_each_rows_campaign(db, scene):
    ev4 = scene.ev4
    cross = await ev4.actor("cross_gm_player")
    roles = await role_map(db, cross.user_id)
    rows = (await db.execute(scoped_select_multi(JournalEntry, roles).options(ENTRY_TAGS))).scalars().all()
    out = await project_all(db, rows, roles)
    by_campaign = {}
    for row, model in zip(rows, out):
        by_campaign.setdefault(row.campaign_id, set()).add(type(model))
    assert by_campaign[ev4.a.campaign_id] == {JournalPartyResponse}
    assert by_campaign[ev4.b.campaign_id] == {JournalGMResponse}
    assert role_ctx(roles, ev4.b.campaign_id).role == "gm" and role_ctx(roles, ev4.a.campaign_id).role == "player"
    with pytest.raises(NotFound):
        role_ctx(roles, RANDOM)


async def test_scoped_select_multi_on_derived_journal_tags(db, scene):
    """journal_tags has no campaign_id: scoped through its entry, per Campaign."""
    cross = await scene.ev4.actor("cross_gm_player")
    roles = await role_map(db, cross.user_id)
    links = (await db.execute(scoped_select_multi(JournalTag, roles))).scalars().all()
    single = (await db.execute(scoped_select(JournalTag, scene.ctxs["player"]))).scalars().all()
    a_links = {(link.journal_id, link.tag_id) for link in links}
    assert {(link.journal_id, link.tag_id) for link in single} <= a_links
    assert (scene.entry, scene.shorthand_tag) not in a_links
    assert (scene.entry, scene.manual_tag) in a_links
    gm_links = (await db.execute(scoped_select(JournalTag, scene.ctxs["gm"]))).scalars().all()
    assert (scene.entry, scene.shorthand_tag) in {(link.journal_id, link.tag_id) for link in gm_links}


async def test_field_visibility_renders_as_the_default(monkeypatch):
    """A registry `field_visibility` hides a field as its schema default
    (None when there is none); the Party schema never names the column."""

    @dataclasses.dataclass
    class Thing:
        id: uuid.UUID
        campaign_id: uuid.UUID
        user_id: uuid.UUID
        visibility: str
        title: str
        secret: str | None
        motto: str
        field_visibility: dict

    class ThingGM(BaseModel):
        id: uuid.UUID
        title: str
        secret: str | None
        motto: str = "unset"

    class ThingParty(BaseModel):
        id: uuid.UUID
        title: str
        secret: str | None
        motto: str = "unset"

    monkeypatch.setitem(REGISTRY, Thing, stored(field_visibility="field_visibility"))
    monkeypatch.setitem(PROJECTIONS, Thing, Projection(ThingGM, ThingParty))
    check_party_schemas()
    cid, uid = uuid.uuid4(), uuid.uuid4()
    thing = Thing(uuid.uuid4(), cid, uid, "party", "T", "S", "M", {"secret": "gm", "motto": "gm", "title": "party"})
    gm = CampaignContext(campaign_id=cid, user_id=uid, role="gm", is_owner=True, audience=GM_AUDIENCE)
    player = audience_ctx(cid, MEMBER_VIEW, by=gm)
    assert project(thing, gm).model_dump() == {"id": thing.id, "title": "T", "secret": "S", "motto": "M"}
    assert project(thing, player).model_dump() == {"id": thing.id, "title": "T", "secret": None, "motto": "unset"}

    class BadParty(ThingParty):
        field_visibility: dict

    monkeypatch.setitem(PROJECTIONS, Thing, Projection(ThingGM, BadParty))
    with pytest.raises(RuntimeError, match="field_visibility"):
        check_party_schemas()


async def test_check_create_refuses_an_unseen_row(scene):
    a = scene.ev4.a.campaign_id
    player, gm = scene.ctxs["player"], scene.ctxs["gm"]
    with pytest.raises(NotFound):
        check_create(NpcEntry(campaign_id=a, user_id=player.user_id, name="x"), player)
    check_create(NpcEntry(campaign_id=a, user_id=gm.user_id, name="x"), gm)
    sheet = dict(campaign_id=a, template_id=uuid.uuid4(), created_by_user_id=player.user_id, name="n", data={})
    check_create(CharacterSheet(**sheet), player)  # default visibility party
    with pytest.raises(NotFound):
        check_create(CharacterSheet(**sheet, visibility="gm"), player)
    with pytest.raises(NotFound):
        check_create(CharacterSheet(**{**sheet, "campaign_id": uuid.uuid4()}), gm)


# ── Share Links ────────────────────────────────────────────────────────────

async def test_share_ctx_live_expired_revoked_and_kind(db, scene):
    ev4 = scene.ev4
    ctx = await share_ctx(db, ev4.a.share_token)
    assert (ctx.role, ctx.read_only, ctx.user_id, ctx.campaign_id) == ("anon", True, None, ev4.a.campaign_id)
    assert ctx.audience.level.value == "public"

    def token(**kw):
        t = CampaignShareToken(campaign_id=ev4.a.campaign_id, created_by_user_id=ev4.a.owner_id,
                               token=uuid.uuid4().hex, **kw)
        db.add(t)
        return t

    now = datetime.now(timezone.utc)
    expired = token(expires_at=now - timedelta(seconds=1))
    future = token(expires_at=now + timedelta(days=1))
    revoked = token(revoked=True)
    collaborate = token(kind="collaborate")
    await db.commit()
    assert (await share_ctx(db, future.token)).campaign_id == ev4.a.campaign_id
    for bad in (expired.token, revoked.token, collaborate.token, "nope", ""):
        with pytest.raises(NotFound):
            await share_ctx(db, bad)
    assert (await resolve_share_token(db, collaborate.token, "collaborate")).kind == "collaborate"
    assert (await resolve_share_token(db, collaborate.token, None)).kind == "collaborate"
    with pytest.raises(NotFound):
        await resolve_share_token(db, ev4.a.share_token, "collaborate")


async def test_share_journals_hide_gm_and_player_kind_entries(client, db, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    player_kind = JournalEntry(user_id=ev4.a.owner_id, campaign_id=a, shorthand="s", narrative="members only",
                               entry_hash=uuid.uuid4().hex, kind="player")
    db.add(player_kind)
    await db.commit()
    token = ev4.a.share_token
    r = await client.get(f"/api/share/{token}/journals")
    ids = {i["id"] for i in r.json()["items"]}
    assert str(scene.gm_entry) not in ids and str(player_kind.id) not in ids and str(scene.entry) in ids
    assert r.json()["total"] == len(ids)
    missing = await client.get(f"/api/share/{token}/journals/{RANDOM}")
    for hidden in (scene.gm_entry, player_kind.id):
        h = await client.get(f"/api/share/{token}/journals/{hidden}")
        assert (h.status_code, h.content) == (missing.status_code, missing.content) == (404, b'{"detail":"Not found"}')
    entry = next(i for i in r.json()["items"] if i["id"] == str(scene.entry))
    assert len(entry["tags"]) == 3 and not find_canaries(r.text)


# ── Routes ─────────────────────────────────────────────────────────────────

async def test_journal_routes_by_role(client, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    gm = (await ev4.actor("gm_owner")).headers
    player = (await ev4.actor("player")).headers
    r = await client.get(f"/api/journals/{scene.entry}", headers=gm)
    assert r.status_code == 200 and "shorthand" in r.json() and len(r.json()["tags"]) == 4
    r = await client.get(f"/api/journals/{scene.entry}", headers=player)
    assert r.status_code == 200 and "shorthand" not in r.json() and len(r.json()["tags"]) == 3
    missing = await client.get(f"/api/journals/{RANDOM}", headers=player)
    hidden = await client.get(f"/api/journals/{scene.gm_entry}", headers=player)
    assert (hidden.status_code, hidden.content) == (missing.status_code, missing.content)
    assert missing.json() == NOT_FOUND
    listing = (await client.get(f"/api/journals/?campaign_id={a}", headers=player)).json()
    assert str(scene.gm_entry) not in {i["id"] for i in listing["items"]}
    assert listing["total"] == len(listing["items"])
    gm_listing = (await client.get(f"/api/journals/?campaign_id={a}", headers=gm)).json()
    assert gm_listing["total"] == listing["total"] + 1
    # tag_id matches visible links only.
    by_shorthand = (await client.get(f"/api/journals/?campaign_id={a}&tag_id={scene.shorthand_tag}",
                                     headers=player)).json()
    assert by_shorthand == {"items": [], "total": 0, "page": 1, "limit": 20}
    by_shorthand_gm = (await client.get(f"/api/journals/?campaign_id={a}&tag_id={scene.shorthand_tag}",
                                        headers=gm)).json()
    assert by_shorthand_gm["total"] == 1
    # Delete of someone else's entry by a Player: the 404, not a 403.
    d = await client.delete(f"/api/journals/{scene.entry}", headers=player)
    assert d.status_code == 404 and d.json() == NOT_FOUND


async def test_tags_counts_only_visible_links(client, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    player = (await ev4.actor("player")).headers
    gm = (await ev4.actor("gm_owner")).headers
    tags = {t["id"]: t for t in (await client.get(f"/api/tags/?campaign_id={a}", headers=player)).json()}
    assert str(scene.shorthand_tag) not in tags
    assert tags[str(scene.hidden_cat_tag)]["custom_category"] is None
    assert tags[str(scene.manual_tag)]["entry_count"] == 1
    gm_tags = {t["id"]: t for t in (await client.get(f"/api/tags/?campaign_id={a}", headers=gm)).json()}
    assert str(scene.shorthand_tag) in gm_tags and gm_tags[str(scene.hidden_cat_tag)]["custom_category"]


async def test_gm_put_npc_and_quest_return_gm_schemas(client, scene):
    ev4 = scene.ev4
    gm = (await ev4.actor("co_gm")).headers
    npc_id, quest_id = ev4.a.ids["npcs"][0], ev4.a.ids["quests"][0]
    r = await client.put(f"/api/npcs/{npc_id}", json={"description": "d"}, headers=gm)
    assert r.status_code == 200 and set(r.json()) == set(NpcGMResponse.model_fields)
    r = await client.put(f"/api/quests/{quest_id}", json={"description": "d"}, headers=gm)
    assert r.status_code == 200 and set(r.json()) == set(QuestGMResponse.model_fields)
    player = (await ev4.actor("player")).headers
    assert (await client.get(f"/api/npcs/?campaign_id={ev4.a.campaign_id}", headers=player)).json() == []


async def test_preview_reads_party_and_writes_404(client, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    gm = {**(await ev4.actor("gm_owner")).headers, **PREVIEW}
    r = await client.get(f"/api/journals/{scene.entry}", headers=gm)
    assert r.status_code == 200 and "shorthand" not in r.json()
    r = await client.get(f"/api/journals/?campaign_id={a}", headers=gm)
    assert all("shorthand" not in i for i in r.json()["items"])
    assert (await client.get(f"/api/npcs/?campaign_id={a}", headers=gm)).json() == []
    assert (await client.get(f"/api/campaigns/{a}", headers=gm)).json()["is_owner"] is False
    for method, url, body in (
        ("PUT", f"/api/npcs/{ev4.a.ids['npcs'][0]}", {"name": "x"}),
        ("POST", "/api/npcs/", {"name": "x", "campaign_id": str(a)}),
        ("DELETE", f"/api/journals/{scene.entry}", None),
        ("POST", f"/api/journals/{scene.entry}/tags", {"name": "x", "tag_type": "item"}),
        ("PATCH", f"/api/character-sheets/templates/{ev4.a.ids['character_sheet_templates'][0]}", {"name": "x"}),
    ):
        r = await client.request(method, url, json=body, headers=gm)
        assert r.status_code == 404 and r.json() == NOT_FOUND, (method, url)


async def test_campaign_routes(client, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    player = (await ev4.actor("player")).headers
    owner = (await ev4.actor("gm_owner")).headers
    r = await client.get(f"/api/campaigns/{a}", headers=owner)
    assert r.status_code == 200 and r.json()["is_owner"] is True and r.json()["owner_display_name"] is None
    r = await client.get(f"/api/campaigns/{a}", headers=player)
    assert r.json()["is_owner"] is False and r.json()["owner_display_name"]
    listing = (await client.get("/api/campaigns/", headers=player)).json()
    assert [c["id"] for c in listing] == [str(a)]
    missing = await client.get(f"/api/campaigns/{RANDOM}", headers=player)
    cross = await ev4.actor("cross_gm_player")
    hidden = await client.get(f"/api/campaigns/{ev4.b.campaign_id}", headers=player)
    assert (hidden.status_code, hidden.content) == (missing.status_code, missing.content)
    mine = (await client.get("/api/campaigns/", headers=cross.headers)).json()
    assert [c["id"] for c in mine] == [str(ev4.b.campaign_id), str(a)]  # owned first


async def test_template_counts_exclude_hidden_sheets(client, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    r = await client.get(f"/api/character-sheets/templates?campaign_id={a}",
                         headers=(await ev4.actor("player")).headers)
    assert [t["character_count"] for t in r.json()] == [0]
    r = await client.get(f"/api/character-sheets/templates?campaign_id={a}",
                         headers=(await ev4.actor("gm_owner")).headers)
    assert [t["character_count"] for t in r.json()] == [1]


# ── Vary ───────────────────────────────────────────────────────────────────

async def test_every_api_response_varies_on_authorization_and_preview(client, scene):
    ev4 = scene.ev4
    for url, headers in ((f"/api/share/{ev4.a.share_token}", {}), ("/api/journals/", {}),
                         (f"/api/journals/{RANDOM}", (await ev4.actor("player")).headers),
                         ("/api/campaigns/", (await ev4.actor("player")).headers)):
        r = await client.get(url, headers=headers)
        vary = [v.strip().lower() for v in r.headers.get("vary", "").split(",")]
        assert "authorization" in vary and "x-lorekeeper-preview" in vary, (url, r.headers.get("vary"))
    # Merged with CORS's Origin, each name once.
    r = await client.get(f"/api/share/{ev4.a.share_token}", headers={"Origin": "http://localhost:5173"})
    vary = [v.strip().lower() for v in r.headers["vary"].split(",")]
    assert {"origin", "authorization", "x-lorekeeper-preview"} <= set(vary) and len(vary) == len(set(vary))


async def test_vary_middleware_unit():
    from app.access import VaryMiddleware

    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"vary", b"Origin, authorization")]})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        sent.append(message)

    await VaryMiddleware(app)({"type": "http", "path": "/api/x"}, None, send)
    assert dict(sent[0]["headers"])[b"vary"] == b"Origin, authorization, X-Lorekeeper-Preview"
    sent.clear()
    await VaryMiddleware(app)({"type": "http", "path": "/docs"}, None, send)
    assert dict(sent[0]["headers"])[b"vary"] == b"Origin, authorization"


async def test_vary_middleware_start_without_headers():
    from app.access import VaryMiddleware

    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204})  # ASGI allows omitting "headers"

    async def send(message):
        sent.append(message)

    await VaryMiddleware(app)({"type": "http", "path": "/api/x"}, None, send)
    assert dict(sent[0]["headers"])[b"vary"] == b"Authorization, X-Lorekeeper-Preview"


# ── Write paths ────────────────────────────────────────────────────────────

async def test_delete_template_refuses_a_cascade_over_hidden_sheets(client, db, scene):
    ev4 = scene.ev4
    template_id = ev4.a.ids["character_sheet_templates"][0]  # has the seeded gm sheet
    sheet_id = ev4.a.ids["character_sheets"][0]
    player = (await ev4.actor("player")).headers
    missing = await client.delete(f"/api/character-sheets/templates/{RANDOM}", headers=player)
    r = await client.delete(f"/api/character-sheets/templates/{template_id}", headers=player)
    assert (r.status_code, r.content) == (missing.status_code, missing.content) == (404, b'{"detail":"Not found"}')
    assert await db.scalar(sa.select(sa.func.count()).where(CharacterSheet.id == sheet_id)) == 1
    gm = (await ev4.actor("gm_owner")).headers
    assert (await client.delete(f"/api/character-sheets/templates/{template_id}", headers=gm)).status_code == 204
    assert await db.scalar(sa.select(sa.func.count()).where(CharacterSheet.id == sheet_id)) == 0


async def test_delete_journal_allowed_paths(client, db, scene):
    ev4 = scene.ev4
    a = ev4.a.campaign_id
    player = await ev4.actor("player")

    def entry(author):
        e = JournalEntry(user_id=author, campaign_id=a, shorthand="s", narrative="n", entry_hash=uuid.uuid4().hex)
        db.add(e)
        return e

    own, players, gms = entry(player.user_id), entry(player.user_id), entry(ev4.a.owner_id)
    await db.commit()
    # E0-Access.5: delete needs `gm` in the entry's Campaign. A Player cannot
    # delete even their own entry (Player Journal deletes arrive with E7).
    r = await client.delete(f"/api/journals/{own.id}", headers=player.headers)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == own.id)) == 1
    owner = (await ev4.actor("gm_owner")).headers
    assert (await client.delete(f"/api/journals/{players.id}", headers=owner)).status_code == 204
    # A Co-GM deletes any entry of the Campaign, the Owner's included.
    co_gm = (await ev4.actor("co_gm")).headers
    assert (await client.delete(f"/api/journals/{gms.id}", headers=co_gm)).status_code == 204
    assert (await client.delete(f"/api/journals/{own.id}", headers=co_gm)).status_code == 204
    for e in (own, players, gms):
        assert await db.scalar(sa.select(sa.func.count()).where(JournalEntry.id == e.id)) == 0


async def test_character_sheet_success_paths_as_a_player(client, scene):
    ev4 = scene.ev4
    a = str(ev4.a.campaign_id)
    player = (await ev4.actor("player")).headers
    t = await client.post("/api/character-sheets/templates", json={
        "campaign_id": a, "name": "Mine", "fields": [{"key": "cls", "label": "Class"}]}, headers=player)
    assert t.status_code == 201 and t.json()["character_count"] == 0, t.text
    s = await client.post("/api/character-sheets/", json={
        "campaign_id": a, "template_id": t.json()["id"], "name": "Pip", "data": {"cls": "Bard"}}, headers=player)
    assert s.status_code == 201 and s.json()["name"] == "Pip", s.text
    sheet_id = s.json()["id"]
    listing = (await client.get(f"/api/character-sheets/?campaign_id={a}", headers=player)).json()
    assert [x["id"] for x in listing] == [sheet_id]
    assert (await client.get(f"/api/character-sheets/{sheet_id}", headers=player)).json()["data"] == {"cls": "Bard"}
    p = await client.patch(f"/api/character-sheets/{sheet_id}", json={"name": "Pippa"}, headers=player)
    assert p.status_code == 200 and p.json()["name"] == "Pippa"
    templates = (await client.get(f"/api/character-sheets/templates?campaign_id={a}", headers=player)).json()
    assert {x["name"]: x["character_count"] for x in templates}["Mine"] == 1
    assert (await client.delete(f"/api/character-sheets/{sheet_id}", headers=player)).status_code == 204
    assert (await client.get(f"/api/character-sheets/{sheet_id}", headers=player)).status_code == 404


async def test_generate_write_response_is_projected(client, scene, monkeypatch):
    from app.api.routes import journals as journal_routes
    from app.services import journal_service

    async def no_dup(*_args):
        return False

    async def noop(*_args):
        return None

    monkeypatch.setattr(journal_routes, "check_hash", no_dup)
    monkeypatch.setattr(journal_service, "store_hash", noop)
    monkeypatch.setattr(journal_service, "extract_tags", lambda _text: [])
    monkeypatch.setattr(journal_service.embedding_service, "embed", lambda _text: None)
    ev4 = scene.ev4
    for who, has_shorthand in (("player", False), ("gm_owner", True)):
        body = {"notes": "GM notes", "campaign_id": str(ev4.a.campaign_id), "entry_hash": uuid.uuid4().hex,
                "narrative": "A narrative."}
        r = await client.post("/api/journals/generate", json=body, headers=(await ev4.actor(who)).headers)
        assert r.status_code == 201, r.text
        assert ("shorthand" in r.json()) is has_shorthand, who


async def test_tag_attach_and_detach_paths(client, db, scene):
    ev4 = scene.ev4
    player = (await ev4.actor("player")).headers
    gm = (await ev4.actor("gm_owner")).headers
    co_gm = (await ev4.actor("co_gm")).headers
    visible_cat = (await db.get(Tag, scene.visible_cat_tag)).custom_category_id
    body = {"name": f"Ilmater {uuid.uuid4().hex[:6]}", "custom_category_id": str(visible_cat)}
    # E0-Access.5: attach and detach need `gm` in the entry's Campaign.
    r = await client.post(f"/api/journals/{scene.entry}/tags", json=body, headers=player)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    r = await client.post(f"/api/journals/{scene.entry}/tags", json=body, headers=co_gm)
    assert r.status_code == 201, r.text
    assert r.json()["custom_category"]["id"] == str(visible_cat)
    r = await client.delete(f"/api/journals/{scene.entry}/tags/{scene.manual_tag}", headers=player)
    assert r.status_code == 404 and r.json() == NOT_FOUND
    # A Co-GM detaches a manual link; the Owner a Shorthand-sourced one.
    assert (await client.delete(f"/api/journals/{scene.entry}/tags/{scene.manual_tag}",
                                headers=co_gm)).status_code == 204
    assert (await client.delete(f"/api/journals/{scene.entry}/tags/{scene.shorthand_tag}",
                                headers=gm)).status_code == 204
    for tag_id in (scene.manual_tag, scene.shorthand_tag):
        assert await db.scalar(sa.select(sa.func.count()).where(
            JournalTag.journal_id == scene.entry, JournalTag.tag_id == tag_id)) == 0
