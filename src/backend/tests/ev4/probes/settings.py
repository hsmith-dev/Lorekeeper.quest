"""EV-4 probes for api/routes/settings.py (E0-QA.13): LLM settings, the
model status, Test Connection and model evaluations are per user. Another
user's saved provider URL, model, API key and evaluation labels are
canaries: an actor never reads them, never gets an answer that moves when
they change, never uses another user's saved key, and cannot delete
another user's evaluation (it answers exactly like a missing one).
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import sqlalchemy as sa

from tests.ev4.families import (
    assert_counts_and_ranking_unchanged, assert_hidden_equals_missing, assert_no_canary,
)
from tests.ev4.fixtures import create_user, mint_canary
from tests.ev4.probes._support import MISSING, authenticated, row_count
from tests.ev4.probes.admin import check_denial
from tests.ev4.probes.retrieval import use_fake_llm
from tests.ev4.registry import ev4_probe
from tests.ev4.report import note_family_call, record_leak

NOBODY = uuid.UUID("00000000-0000-4000-8000-00000000e4a2")  # no actor is GM here


def _canary(kind: str) -> str:
    return mint_canary(kind, NOBODY).token


async def other_user(ev4):
    """Another user with canary LLM settings and one canary evaluation.
    Returns (user id, evaluation id)."""
    from app.db.models.user_settings import UserSettings

    user = await create_user(ev4.db, "settings_other")
    ev4.db.add(UserSettings(user_id=user.id, llm_provider="fake", llm_api_url=f"http://{_canary('XLLMURL')}",
                            llm_api_key=_canary("XLLMKEY"), llm_model=_canary("XLLMMODEL")))
    await ev4.db.commit()
    return user.id, await add_evaluation(ev4, user.id, _canary("XEVAL"))


async def add_evaluation(ev4, user_id, label: str) -> uuid.UUID:
    from app.db.models.model_evaluation import ModelEvaluation

    ev = ModelEvaluation(id=uuid.uuid4(), user_id=user_id, label=label, sample_size=1, avg_length=1.0,
                         avg_word_overlap=0.5, avg_semantic_similarity=0.5, has_content_pct=100.0, error_count=0)
    ev4.db.add(ev)
    await ev4.db.commit()
    return ev.id


async def change_other(ev4, user_id) -> None:
    """Changes only the other user may see: new settings and a new evaluation."""
    from app.db.models.user_settings import UserSettings

    await ev4.db.execute(sa.update(UserSettings).where(UserSettings.user_id == user_id).values(
        llm_model=_canary("XLLMMODEL"), llm_api_url=f"http://{_canary('XLLMURL')}", llm_provider="openai",
        hosted_model_variant="base",
    ))
    await ev4.db.commit()
    await add_evaluation(ev4, user_id, _canary("XEVAL"))


async def _settings_row(ev4, user_id):
    from app.db.models.user_settings import UserSettings

    return tuple((await ev4.db.execute(sa.select(
        UserSettings.llm_provider, UserSettings.llm_api_url, UserSettings.llm_api_key, UserSettings.llm_model,
    ).where(UserSettings.user_id == user_id))).one())


async def _per_user_read(ev4, actor, url: str) -> None:
    other, _ = await other_user(ev4)
    r = await actor.get(url)
    if not authenticated(actor):
        check_denial(actor, r, f"GET {url}")
        return
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text
    await assert_counts_and_ranking_unchanged(actor, url, lambda: change_other(ev4, other))


@ev4_probe("GET", "/api/settings/")
async def probe_get_settings(ev4, actor):
    await _per_user_read(ev4, actor, "/api/settings/")


@ev4_probe("GET", "/api/settings/model-status")
async def probe_model_status(ev4, actor):
    # The actor's own provider is the fake one, so the answer never needs
    # the local model server (CI has none).
    await use_fake_llm(ev4, actor)
    await _per_user_read(ev4, actor, "/api/settings/model-status")


@ev4_probe("PUT", "/api/settings/")
async def probe_put_settings(ev4, actor):
    other, _ = await other_user(ev4)
    before = await _settings_row(ev4, other)
    r = await actor.put("/api/settings/", json={"llm_model": "my-own-model", "llm_api_key": "my-own-key"})
    if not authenticated(actor):
        check_denial(actor, r, "PUT /api/settings/")
    else:
        assert_no_canary(actor, r)
        assert r.status_code == 200 and r.json()["llm_model"] == "my-own-model", r.text
    note_family_call()
    if await _settings_row(ev4, other) != before:
        record_leak(f"EV-4 leak: {actor.name}'s settings write changed another user's settings", [str(other)])


@ev4_probe("POST", "/api/settings/test")
async def probe_test_connection(ev4, actor):
    """No URL or key in the body: the route falls back to the caller's own
    saved settings (none here), never another user's canary URL or key."""
    await other_user(ev4)
    r = await actor.post("/api/settings/test", json={"llm_provider": "fake"})
    if not authenticated(actor):
        check_denial(actor, r, "POST /api/settings/test")
        return
    assert_no_canary(actor, r)
    assert r.status_code == 200, r.text


@contextmanager
def fake_evaluation():
    """run_evaluation without the (uncommitted) validation set: a fixed result."""
    from app.api.routes import settings as route

    real = route.run_evaluation

    async def fake(cfg, sample_size):
        return {"sample_size": sample_size, "avg_length": 0.0, "avg_word_overlap": 0.0,
                "avg_semantic_similarity": 0.0, "has_content_pct": 0.0, "error_count": 0}

    route.run_evaluation = fake
    try:
        yield
    finally:
        route.run_evaluation = real


@ev4_probe("POST", "/api/settings/evaluate")
async def probe_evaluate(ev4, actor):
    from app.db.models.model_evaluation import ModelEvaluation

    other, _ = await other_user(ev4)
    await use_fake_llm(ev4, actor)
    before = await row_count(ev4, ModelEvaluation, ModelEvaluation.user_id == other)
    with fake_evaluation():
        r = await actor.post("/api/settings/evaluate", json={"label": "mine", "sample_size": 1})
    if not authenticated(actor):
        check_denial(actor, r, "POST /api/settings/evaluate")
    else:
        assert_no_canary(actor, r)
        assert r.status_code == 201, r.text
        assert await row_count(ev4, ModelEvaluation, ModelEvaluation.id == uuid.UUID(r.json()["id"]),
                               ModelEvaluation.user_id == actor.user_id) == 1
    note_family_call()
    if await row_count(ev4, ModelEvaluation, ModelEvaluation.user_id == other) != before:
        record_leak(f"EV-4 leak: {actor.name}'s evaluation was stored for another user", [str(other)])


@ev4_probe("GET", "/api/settings/evaluations")
async def probe_list_evaluations(ev4, actor):
    other, _ = await other_user(ev4)
    url = "/api/settings/evaluations"
    r = await actor.get(url)
    if not authenticated(actor):
        check_denial(actor, r, f"GET {url}")
        return
    own = await add_evaluation(ev4, actor.user_id, "mine")
    r = await actor.get(url)
    assert_no_canary(actor, r)
    assert r.status_code == 200 and [e["id"] for e in r.json()] == [str(own)], r.text
    await assert_counts_and_ranking_unchanged(actor, url, lambda: change_other(ev4, other))


@ev4_probe("DELETE", "/api/settings/evaluations/{evaluation_id}")
async def probe_delete_evaluation(ev4, actor):
    from app.db.models.model_evaluation import ModelEvaluation

    _, theirs = await other_user(ev4)
    await assert_hidden_equals_missing(actor, f"/api/settings/evaluations/{theirs}",
                                       f"/api/settings/evaluations/{MISSING}", method="DELETE")
    assert await row_count(ev4, ModelEvaluation, ModelEvaluation.id == theirs) == 1
    if not authenticated(actor):
        return
    own = await add_evaluation(ev4, actor.user_id, "mine")
    r = await actor.delete(f"/api/settings/evaluations/{own}")
    assert r.status_code == 204, r.text
    assert await row_count(ev4, ModelEvaluation, ModelEvaluation.id == own) == 0
