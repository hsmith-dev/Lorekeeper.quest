"""seeds/demo_campaign.json and scripts/seed_demo.py (E0-QA.12)."""

import copy
import json
import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models.campaign import Campaign
from app.db.models.journal import JournalEntry
from app.db.models.npc import NpcEntry, NpcStatus
from app.db.models.quest import Quest
from app.db.models.user import User
from app.schemas.share import PublicJournalResponse, PublicNpcResponse, PublicQuestResponse
from scripts import seed_demo
from scripts.eval_common import FakeEmbeddingModel
from scripts.eval_retrieval import LABELED
from scripts.seed_demo import SeedError
from tests.conftest import TEST_DB_URL

SEED = seed_demo.read_seed(seed_demo.DEFAULT_SEED_PATH)
FAKE = FakeEmbeddingModel()


def fake_embedder(text: str) -> list[float]:
    return FAKE.encode(text).tolist()


def _email() -> str:
    return f"seed_{uuid.uuid4().hex[:10]}@example.com"


async def _seed_in_new_session(seed=SEED, owner_email=None, embedder=None):
    engine = create_async_engine(TEST_DB_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            return await seed_demo.seed_campaign(s, seed, owner_email, embedder)
    finally:
        await engine.dispose()


async def _counts(db, campaign_id) -> dict[str, int]:
    out = {}
    for name, model in (("entries", JournalEntry), ("npcs", NpcEntry), ("quests", Quest)):
        out[name] = await db.scalar(
            sa.select(sa.func.count()).select_from(model).where(model.campaign_id == campaign_id)
        )
    return out


# ── The seed file itself ────────────────────────────────────────────────────

def test_seed_file_shape():
    assert SEED["format_version"] == 1
    entries = SEED["entries"]
    assert len(entries) == 12
    assert [e["purpose"] for e in entries].count("demo") == 9
    evals = [e for e in entries if e["purpose"] == "eval"]
    assert sorted(e["eval_label"]["kind"] for e in evals) == ["contradiction", "death", "flashback"]
    for e in entries:
        for f in ("seed_id", "session_number", "session_date", "shorthand", "narrative", "purpose"):
            assert e[f], (e["seed_id"], f)
    ids = [x["seed_id"] for k in ("entries", "npcs", "quests", "locations", "gm_secrets") for x in SEED[k]]
    assert len(ids) == len(set(ids))
    assert [e["session_number"] for e in entries] == list(range(1, 13))
    roles = {n["role"] for n in SEED["npcs"]}
    assert {"pc", "npc", "monster", "faction"} <= roles
    assert SEED["quests"] and SEED["locations"]


def test_eval_labels_reference_real_entries():
    ids = {e["seed_id"] for e in SEED["entries"]}
    contradiction = next(e for e in SEED["entries"] if e.get("eval_label", {}).get("kind") == "contradiction")
    assert contradiction["eval_label"]["contradicts"] in ids
    mira = next(n for n in SEED["npcs"] if n["name"] == "Mira")
    assert mira["status_history"][-1] == {"session": 10, "status": "dead"}


def test_every_labelled_substring_matches_exactly_one_demo_entry():
    # eval_retrieval.py scores a hit by these substrings (case-insensitive),
    # so each must point at one demo entry and nothing else.
    subs = {s for _, exp in LABELED for s in exp}
    owners = {}
    for sub in subs:
        matches = [e for e in SEED["entries"] if sub.lower() in e["shorthand"].lower()]
        assert len(matches) == 1, (sub, [m["seed_id"] for m in matches])
        assert matches[0]["purpose"] == "demo", sub
        owners[sub] = matches[0]["seed_id"]
    # One label per demo entry, as in the original 9-entry campaign.
    assert len(subs) == 9
    assert len(set(owners.values())) == 9


def test_gm_secrets_only_in_gm_only_fields():
    # The Public* share schemas leave these fields out.
    assert "shorthand" not in PublicJournalResponse.model_fields
    assert "notes" not in PublicNpcResponse.model_fields
    assert "notes" not in PublicQuestResponse.model_fields

    lookup = {
        "entry": {e["seed_id"]: e for e in SEED["entries"]},
        "npc": {n["seed_id"]: n for n in SEED["npcs"]},
        "quest": {q["seed_id"]: q for q in SEED["quests"]},
    }
    public = seed_demo.public_texts(SEED)
    phrases = [s["phrase"] for s in SEED["gm_secrets"]]
    assert len(phrases) == len(set(phrases)) >= 3
    kinds = {s["where"]["kind"] for s in SEED["gm_secrets"]}
    assert kinds == {"entry", "npc", "quest"}
    for s in SEED["gm_secrets"]:
        w = s["where"]
        assert w["field"] in seed_demo.GM_ONLY_FIELDS[w["kind"]]
        assert s["phrase"] in lookup[w["kind"]][w["seed_id"]][w["field"]]
        assert not any(s["phrase"].lower() in t.lower() for t in public), s["phrase"]
        # Unique phrase: it occurs in exactly one place in the whole file.
        assert json.dumps(SEED).lower().count(s["phrase"].lower()) == 2  # the field + the gm_secrets entry


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["entries"][1].__setitem__("seed_id", s["entries"][0]["seed_id"]), "duplicate seed_id"),
    (lambda s: s["entries"][0].pop("narrative"), "missing field 'narrative'"),
    (lambda s: s.pop("gm_secrets"), "missing field 'gm_secrets'"),
    (lambda s: s["gm_secrets"][0]["where"].__setitem__("field", "narrative"), "not a GM-only field"),
    (lambda s: s["npcs"][0].__setitem__("description", s["gm_secrets"][2]["phrase"]), "public field"),
    (lambda s: s["entries"][0].__setitem__("session_date", "Jan 10"), "session_date"),
])
def test_validate_seed_rejects(mutate, message):
    bad = copy.deepcopy(SEED)
    mutate(bad)
    with pytest.raises(SeedError, match=message):
        seed_demo.validate_seed(bad)


def test_bad_seed_exits_1_before_touching_the_db(tmp_path, capsys):
    bad = copy.deepcopy(SEED)
    bad["entries"][1]["seed_id"] = bad["entries"][0]["seed_id"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    # An unreachable URL: reaching it would fail differently (and slowly).
    rc = seed_demo.main(["--seed", str(path), "--database-url",
                         "postgresql+asyncpg://nobody:x@127.0.0.1:1/nothing_test", "--embeddings", "skip"])
    assert rc == 1
    assert "duplicate seed_id" in capsys.readouterr().err


# ── Embedding model, offline ────────────────────────────────────────────────

class _Refuse:
    calls: list = []

    def __init__(self, name, **kwargs):
        _Refuse.calls.append((name, kwargs))
        raise OSError("not in cache")


def test_offline_auto_warns_and_require_exits(monkeypatch, capsys):
    import sentence_transformers

    _Refuse.calls = []
    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _Refuse)
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")  # restored after the test
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")

    assert seed_demo.load_embedder("auto") is None
    assert "warning" in capsys.readouterr().err
    assert _Refuse.calls == [(seed_demo.EMBEDDING_MODEL, {"local_files_only": True})]
    assert os.environ["HF_HUB_OFFLINE"] == "1"

    with pytest.raises(SeedError, match="not in the local cache"):
        seed_demo.load_embedder("require")

    _Refuse.calls = []
    assert seed_demo.load_embedder("skip") is None
    assert _Refuse.calls == []


def test_require_exits_1(monkeypatch, capsys):
    import sentence_transformers

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", _Refuse)
    rc = seed_demo.main(["--database-url", "postgresql+asyncpg://nobody:x@127.0.0.1:1/nothing_test",
                         "--embeddings", "require"])
    assert rc == 1
    assert "not in the local cache" in capsys.readouterr().err


# ── Against the test DB ─────────────────────────────────────────────────────

async def test_double_seed_is_idempotent(db):
    email = _email()
    first = await _seed_in_new_session(owner_email=email)
    assert first.user_created and first.campaign_created
    assert first.created == {"entries": 12, "npcs": len(SEED["npcs"]), "quests": len(SEED["quests"])}
    assert first.embedded == 0

    second = await _seed_in_new_session(owner_email=email)
    assert second.created_total == 0
    assert "created 0 " in second.summary()
    assert second.campaign_id == first.campaign_id
    assert second.entry_ids == first.entry_ids

    counts = await _counts(db, first.campaign_id)
    assert counts == {"entries": 12, "npcs": len(SEED["npcs"]), "quests": len(SEED["quests"])}
    assert await db.scalar(sa.select(sa.func.count()).select_from(User).where(User.email == email)) == 1
    assert await db.scalar(
        sa.select(sa.func.count()).select_from(Campaign).where(Campaign.user_id == first.owner_id)
    ) == 1


async def test_existing_owner_is_untouched(db):
    email = _email()
    user = User(email=email, display_name="Real GM", hashed_password="keep-me")
    db.add(user)
    await db.commit()

    res = await _seed_in_new_session(owner_email=email)
    assert not res.user_created
    assert res.owner_id == user.id
    await db.refresh(user)
    assert (user.display_name, user.hashed_password) == ("Real GM", "keep-me")


async def test_rows_match_the_seed(db):
    res = await _seed_in_new_session(owner_email=_email())
    entries = (await db.scalars(
        sa.select(JournalEntry).where(JournalEntry.campaign_id == res.campaign_id)
    )).all()
    by_hash = {e.entry_hash: e for e in entries}
    for e in SEED["entries"]:
        row = by_hash[seed_demo.entry_hash(res.campaign_id, e["seed_id"])]
        assert row.shorthand == e["shorthand"] and row.narrative == e["narrative"]
        assert row.session_date.isoformat() == e["session_date"]
        assert row.narrative_tsv is not None
        assert row.embedding is None  # no embedder

    # tsv covers shorthand + narrative: "party" is only in e01's shorthand.
    e01 = by_hash[seed_demo.entry_hash(res.campaign_id, "e01-old-mill")]
    assert "party" not in e01.narrative.lower()
    hit = await db.scalar(sa.select(JournalEntry.id).where(
        JournalEntry.id == e01.id,
        JournalEntry.narrative_tsv.op("@@")(sa.func.plainto_tsquery("english", "party")),
    ))
    assert hit == e01.id

    mira = await db.scalar(sa.select(NpcEntry).where(
        NpcEntry.campaign_id == res.campaign_id, NpcEntry.name == "Mira"))
    assert mira.status == NpcStatus.dead

    # GM secrets stay out of what a share viewer is served.
    phrases = [s["phrase"] for s in SEED["gm_secrets"]]
    npcs = (await db.scalars(sa.select(NpcEntry).where(NpcEntry.campaign_id == res.campaign_id))).all()
    quests = (await db.scalars(sa.select(Quest).where(Quest.campaign_id == res.campaign_id))).all()
    public = " ".join(
        [PublicNpcResponse.model_validate(n).model_dump_json() for n in npcs]
        + [PublicQuestResponse.model_validate(q).model_dump_json() for q in quests]
        + [e.narrative for e in entries]
    )
    private = " ".join([e.shorthand for e in entries] + [n.notes or "" for n in npcs] + [q.notes or "" for q in quests])
    for p in phrases:
        assert p not in public and p in private, p


async def test_embeddings_filled_once_a_model_is_available(db):
    email = _email()
    first = await _seed_in_new_session(owner_email=email, embedder=None)
    assert first.embedded == 0

    second = await _seed_in_new_session(owner_email=email, embedder=fake_embedder)
    assert second.created_total == 0
    assert second.embedded == 12
    assert "embedded 12" in second.summary()

    third = await _seed_in_new_session(owner_email=email, embedder=fake_embedder)
    assert third.embedded == 0 and third.created_total == 0

    e01 = await db.scalar(sa.select(JournalEntry).where(
        JournalEntry.entry_hash == seed_demo.entry_hash(first.campaign_id, "e01-old-mill")))
    expected = fake_embedder(seed_demo.entry_text(e01.shorthand, e01.narrative))
    assert list(e01.embedding) == pytest.approx(expected, abs=1e-6)
