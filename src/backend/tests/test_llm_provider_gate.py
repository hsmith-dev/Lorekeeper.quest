"""E0-LLM.2: llm_provider's use of the gate and the fixed local model.

The LLM backends are an httpx.MockTransport (llm_provider._transport) and the
gate is a fakeredis-backed LLMGate swapped in for llm_gate.get_gate, so no
test opens a socket to KOBOLD_URL or needs a Redis server.
"""

import json
import uuid
from types import SimpleNamespace

import fakeredis
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import llm_gate
from app.core.config import get_settings
from app.core.errors import LLMBusy
from app.core.llm_gate import GateClass, LLMGate
from app.services import llm_provider
from app.services.llm_provider import (
    LLMConfig,
    complete_messages,
    model_for,
    stream_messages,
    strip_local_options,
    uses_platform_llm,
)

MESSAGES = [{"role": "user", "content": "Hello"}]
STREAM_CHUNKS = ["Once ", "upon ", "a time"]


def platform_cfg(**kwargs) -> LLMConfig:
    return LLMConfig(provider="kobold", api_url=get_settings().kobold_url, **kwargs)


class Backend:
    """OpenAI-compatible chat completions, plain and streamed. KoboldCpp's
    native /api/v1/generate always 404s (as on Ollama), and `status` can make
    chat completions fail too."""

    def __init__(self):
        self.payloads: list[dict] = []
        self.hosts: list[str] = []
        self.native_calls = 0
        self.status = 200

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/generate":
            self.native_calls += 1
            return httpx.Response(404, text="404 page not found")
        payload = json.loads(await request.aread())
        self.payloads.append(payload)
        self.hosts.append(request.url.host)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "model loading"})
        if payload.get("stream"):
            lines = [
                "data: " + json.dumps({"choices": [{"delta": {"content": c}}]})
                for c in STREAM_CHUNKS
            ] + ["data: [DONE]"]
            return httpx.Response(200, text="\n\n".join(lines) + "\n\n")
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})


@pytest.fixture
def backend(monkeypatch) -> Backend:
    b = Backend()
    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(b.handler))
    return b


class RecordingGate(LLMGate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.acquired: list[GateClass] = []

    async def acquire(self, cls, *, wait_s=None):
        self.acquired.append(GateClass(cls))
        return await super().acquire(cls, wait_s=wait_s)

    async def holder_count(self) -> int:
        return await self.redis.zcard(self.holders_key)


@pytest_asyncio.fixture
async def gate(monkeypatch):
    redis = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    g = RecordingGate(redis, capacity=1, wait_s=1, poll_s=0.01, key_prefix=f"test_gate:{uuid.uuid4().hex}")
    monkeypatch.setattr(llm_gate, "get_gate", lambda: g)
    yield g
    await redis.aclose()


class GateTouched(Exception):
    pass


@pytest.fixture
def no_gate(monkeypatch):
    def touched():
        raise GateTouched("BYOK call reached the gate")

    monkeypatch.setattr(llm_gate, "get_gate", touched)


# --- gating --------------------------------------------------------------


async def test_platform_call_uses_default_class(backend, gate):
    assert await complete_messages(MESSAGES, platform_cfg()) == "OK"
    assert gate.acquired == [GateClass.gm_interactive]
    assert await gate.holder_count() == 0


async def test_no_config_is_platform(backend, gate):
    await complete_messages(MESSAGES)
    assert gate.acquired == [GateClass.gm_interactive]


async def test_explicit_gate_class(backend, gate):
    await complete_messages(MESSAGES, platform_cfg(), gate_class=GateClass.live_recap)
    await complete_messages(MESSAGES, platform_cfg(), gate_class="job_backfill")
    assert gate.acquired == [GateClass.live_recap, GateClass.job_backfill]


async def test_current_class_contextvar(backend, gate):
    token = llm_gate.current_class.set(GateClass.job_onsave)
    try:
        await complete_messages(MESSAGES, platform_cfg())
    finally:
        llm_gate.current_class.reset(token)
    assert gate.acquired == [GateClass.job_onsave]


async def test_outer_slot_makes_inner_call_reentrant(backend, gate):
    async with llm_gate.llm_slot(GateClass.live_recap):
        await complete_messages(MESSAGES, platform_cfg())
        await complete_messages(MESSAGES, platform_cfg())
    assert gate.acquired == [GateClass.live_recap]


async def test_busy_gate_raises_llm_busy(backend, gate):
    held = await gate.acquire(GateClass.live_recap)
    try:
        token = llm_gate.current_deadline.set(0.0)  # already expired
        try:
            with pytest.raises(LLMBusy):
                await complete_messages(MESSAGES, platform_cfg())
        finally:
            llm_gate.current_deadline.reset(token)
    finally:
        await held.release()
    assert backend.payloads == []


@pytest.mark.parametrize(
    "cfg",
    [
        LLMConfig(provider="openai", api_key="sk-test"),
        LLMConfig(provider="kobold", api_url="http://my-own-kobold.test:5001"),
        LLMConfig(provider="custom", api_url="http://custom.test:8000"),
    ],
    ids=["openai", "kobold-own-url", "custom"],
)
async def test_byok_never_touches_gate(backend, no_gate, cfg):
    assert await complete_messages(MESSAGES, cfg) == "OK"
    chunks = [c async for c in stream_messages(MESSAGES, cfg)]
    assert "".join(chunks) == "".join(STREAM_CHUNKS)
    assert await llm_provider.reserve_slot(cfg) is not None


def test_uses_platform_llm():
    url = get_settings().kobold_url
    assert uses_platform_llm(LLMConfig())
    assert uses_platform_llm(LLMConfig(provider="kobold", api_url=url + "/"))
    assert uses_platform_llm(LLMConfig(provider="kobold", api_url=""))
    assert not uses_platform_llm(LLMConfig(provider="kobold", api_url="http://elsewhere.test:5001"))
    assert not uses_platform_llm(LLMConfig(provider="openai", api_url=url))


# --- fixed local model -------------------------------------------------------


@pytest.fixture
def distinct_local_model(monkeypatch) -> str:
    """LOCAL_LLM_MODEL set to something other than KOBOLD_MODEL."""
    monkeypatch.setattr(get_settings(), "local_llm_model", "fixed-local-model")
    return "fixed-local-model"


def test_model_for(distinct_local_model):
    s = get_settings()
    base = platform_cfg(model=s.kobold_base_model)
    fine_tuned = platform_cfg(model=s.kobold_model)  # what the default config carries
    assert model_for(None, fine_tuned) == distinct_local_model
    assert model_for("chat", base) == distinct_local_model
    assert model_for("narrative", base) == s.kobold_base_model
    assert model_for("narrative", fine_tuned) == distinct_local_model
    assert model_for("narrative", platform_cfg()) == distinct_local_model
    assert model_for("narrative", platform_cfg(model="something-else")) == distinct_local_model
    assert model_for("chat", LLMConfig(provider="openai", model="gpt-4o")) == "gpt-4o"
    assert model_for("chat", LLMConfig(provider="kobold", api_url="http://own.test", model="mine")) == "mine"
    assert model_for("chat", LLMConfig(provider="anthropic")) is None


def _settings(monkeypatch, **kwargs):
    from app.core.config import Settings

    for var in ("LLM_GATE_CAPACITY", "OLLAMA_NUM_PARALLEL", "LOCAL_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None, database_url="postgresql+asyncpg://u:p@localhost/x_test",
        postgres_password="p", secret_key="s", **kwargs,
    )


def test_local_llm_model_defaults_to_kobold_model(monkeypatch):
    s = _settings(monkeypatch, local_llm_model="", kobold_model="km-test")
    assert s.local_llm_model == "km-test"
    assert _settings(monkeypatch, local_llm_model="lm-test").local_llm_model == "lm-test"


def test_gate_capacity_from_ollama_num_parallel(monkeypatch):
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "2")
    from app.core.config import Settings

    base = dict(_env_file=None, database_url="postgresql+asyncpg://u:p@localhost/x_test",
                postgres_password="p", secret_key="s")
    assert Settings(**base).llm_gate_capacity == 2
    monkeypatch.setenv("OLLAMA_NUM_PARALLEL", "0")  # Ollama's "auto"
    assert Settings(**base).llm_gate_capacity == 1
    monkeypatch.delenv("OLLAMA_NUM_PARALLEL")
    assert Settings(**base).llm_gate_capacity == 1


async def test_platform_payload_names_distinct_local_model(backend, gate, distinct_local_model):
    s = get_settings()
    await complete_messages(MESSAGES, platform_cfg(model=s.kobold_model))
    await complete_messages(MESSAGES, platform_cfg(model=s.kobold_model), task="narrative")
    [c async for c in stream_messages(MESSAGES, platform_cfg(model=s.kobold_model))]
    assert [p["model"] for p in backend.payloads] == [distinct_local_model] * 3


async def test_non_streaming_payload_never_streams(backend, gate):
    assert await complete_messages(MESSAGES, platform_cfg(), options={"stream": True}) == "OK"
    assert backend.payloads[0]["stream"] is False


# --- narrative call sites keep the base variant, in one slot ----------------


async def test_generate_narrative_one_slot_base_model(backend, gate):
    from app.services import ai_service

    s = get_settings()
    out = await ai_service.generate_narrative("We met a dragon.", config=platform_cfg(model=s.kobold_base_model))
    assert out == "OK"
    assert backend.native_calls == 3  # native attempt failed, fell back
    assert [p["model"] for p in backend.payloads] == [s.kobold_base_model]
    assert gate.acquired == [GateClass.gm_interactive]
    assert await gate.holder_count() == 0


async def test_provider_connection_names_base_model(backend, gate):
    s = get_settings()
    assert await llm_provider.test_provider_connection(platform_cfg(model=s.kobold_base_model)) == "OK"
    assert backend.payloads[0]["model"] == s.kobold_base_model


async def test_run_evaluation_names_base_model(backend, gate, monkeypatch):
    from app.services import eval_service

    s = get_settings()
    record = {"instruction": "Expand the notes.", "input": "dragon", "output": "A dragon appeared."}
    monkeypatch.setattr(eval_service, "_load_validation_set", lambda: [record])
    monkeypatch.setattr(eval_service, "_score", lambda ref, gen: {
        "length": len(gen), "word_overlap": 0.0, "semantic_similarity": 0.0, "has_content": False,
    })
    result = await eval_service.run_evaluation(platform_cfg(model=s.kobold_base_model), 1)
    assert result["error_count"] == 0
    assert [p["model"] for p in backend.payloads] == [s.kobold_base_model]


async def test_payload_uses_fixed_model_except_narrative(backend, gate):
    s = get_settings()
    base = platform_cfg(model=s.kobold_base_model)
    await complete_messages(MESSAGES, base)
    await complete_messages(MESSAGES, base, task="narrative")
    [c async for c in stream_messages(MESSAGES, base)]
    assert [p["model"] for p in backend.payloads] == [s.local_llm_model, s.kobold_base_model, s.local_llm_model]


async def test_byok_kobold_keeps_fallback_model(backend, no_gate):
    await complete_messages(MESSAGES, LLMConfig(provider="kobold", api_url="http://own.test:5001"))
    assert backend.payloads[0]["model"] == get_settings().kobold_model


# --- option stripping ------------------------------------------------------

OPTIONS = {"num_ctx": 8192, "num_gpu": 0, "keep_alive": "5m", "top_p": 0.9}


def test_strip_local_options():
    assert strip_local_options(OPTIONS) == {"top_p": 0.9}
    assert strip_local_options(None) == {}
    assert "num_ctx" in OPTIONS  # input not mutated


@pytest.mark.parametrize(
    "cfg",
    [platform_cfg(), LLMConfig(provider="openai", api_key="sk-test")],
    ids=["platform", "openai"],
)
async def test_options_stripped_from_payloads(backend, gate, cfg):
    await complete_messages(MESSAGES, cfg, options=OPTIONS)
    [c async for c in stream_messages(MESSAGES, cfg, options=OPTIONS)]
    assert len(backend.payloads) == 2
    for p in backend.payloads:
        assert p["top_p"] == 0.9
        assert not {"num_ctx", "num_gpu", "keep_alive"} & set(p)


async def test_explicit_args_win_over_options(backend, gate):
    await complete_messages(MESSAGES, platform_cfg(), temperature=0.1, options={"temperature": 1.5, "model": "x"})
    assert backend.payloads[0]["temperature"] == 0.1
    assert backend.payloads[0]["model"] == get_settings().local_llm_model


# --- streaming holds one slot for the whole stream ---------------------------


async def test_stream_releases_on_normal_end(backend, gate):
    chunks = []
    async for c in stream_messages(MESSAGES, platform_cfg()):
        assert await gate.holder_count() == 1
        chunks.append(c)
    assert chunks == STREAM_CHUNKS
    assert gate.acquired == [GateClass.gm_interactive]
    assert await gate.holder_count() == 0


async def test_stream_releases_on_aclose_mid_stream(backend, gate):
    agen = stream_messages(MESSAGES, platform_cfg(), gate_class=GateClass.player_interactive)
    assert await agen.__anext__() == STREAM_CHUNKS[0]
    assert await gate.holder_count() == 1
    await agen.aclose()
    assert await gate.holder_count() == 0
    assert gate.acquired == [GateClass.player_interactive]


async def test_stream_slot_not_held_in_consumer_context(backend, gate):
    # The stream's slot belongs to the stream, not to whoever iterates it: a
    # call the consumer makes mid-stream must queue (busy at capacity 1), not
    # silently bypass the gate as a reentrant no-op.
    agen = stream_messages(MESSAGES, platform_cfg())
    await agen.__anext__()
    with pytest.raises(LLMBusy):
        await llm_gate.acquire(GateClass.live_recap, wait_s=0)
    await agen.aclose()
    assert await gate.holder_count() == 0


async def test_reserved_slot_covers_stream(backend, gate):
    slot = await llm_provider.reserve_slot(platform_cfg(), GateClass.live_recap)
    try:
        with slot.held():
            assert "".join([c async for c in stream_messages(MESSAGES, platform_cfg())])
    finally:
        await slot.release()
    assert gate.acquired == [GateClass.live_recap]
    assert await gate.holder_count() == 0


# --- SSE route -----------------------------------------------------------


def fake_prep():
    """Just enough of chat._ChatPrep for event_stream (no DB, no retrieval)."""
    return SimpleNamespace(
        session=SimpleNamespace(id=uuid.uuid4()),
        sources=[],
        canon_sources=[],
        grounded=lambda: False,
        retrieval_debug=lambda: SimpleNamespace(model_dump=lambda: {}),
        chat_messages=MESSAGES,
    )


async def post_chat_stream(monkeypatch, persisted: list | None = None):
    from app.api.deps import get_current_user, get_user_llm_config
    from app.api.routes import chat as chat_routes
    from app.core.limiter import limiter
    from app.db.session import get_db
    from app.main import app

    async def prepare(body, user, db, config):
        return fake_prep()

    async def persist(*args, **kwargs):
        if persisted is not None:
            persisted.append(args)

    monkeypatch.setattr(chat_routes, "_prepare_chat", prepare)
    monkeypatch.setattr(chat_routes, "_persist_chat_turn", persist)
    limiter.reset()
    user = SimpleNamespace(id=uuid.uuid4(), access_granted=True)
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_user_llm_config] = lambda: platform_cfg()
    app.dependency_overrides[get_db] = lambda: None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/chat/stream", json={"message": "Who is the BBEG?"})
    finally:
        app.dependency_overrides.clear()


async def test_chat_stream_takes_one_slot_and_releases_it(backend, gate, monkeypatch):
    persisted: list = []
    r = await post_chat_stream(monkeypatch, persisted)
    assert r.status_code == 200
    assert "event: done" in r.text and "upon" in r.text
    assert len(persisted) == 1
    assert gate.acquired == [GateClass.gm_interactive]  # stream_messages reused the reserved slot
    assert await gate.holder_count() == 0


async def test_chat_stream_upstream_error_event(backend, gate, monkeypatch):
    backend.status = 503
    persisted: list = []
    r = await post_chat_stream(monkeypatch, persisted)
    assert r.status_code == 200  # the stream had already started
    assert "event: error" in r.text
    assert "event: done" not in r.text
    assert persisted == []
    assert await gate.holder_count() == 0


async def test_chat_stream_busy_is_plain_503(monkeypatch):
    async def busy(cfg, gate_class=None):
        raise LLMBusy("The AI model is busy right now. Please try again in a moment.")

    def stream_must_not_run(*args, **kwargs):
        raise AssertionError("stream started despite a busy gate")

    monkeypatch.setattr(llm_provider, "reserve_slot", busy)
    monkeypatch.setattr(llm_provider, "stream_messages", stream_must_not_run)
    r = await post_chat_stream(monkeypatch)
    assert r.status_code == 503
    assert r.json()["code"] == "llm_busy"
    assert not r.headers["content-type"].startswith("text/event-stream")
