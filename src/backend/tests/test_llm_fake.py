"""E0-LLM.5: the deterministic fake LLM provider and llm_provider.capture().

Under ENVIRONMENT=test every config without a MockTransport is answered by
llm_provider.fake_llm; the platform-LLM gate still runs, so it is a
fakeredis LLMGate here. The no_kobold_socket guard (tests/fixtures/fake_llm.py)
fails any test that opens a socket to KOBOLD_URL.
"""

import dataclasses
import errno
import json
import logging
import socket
import uuid
from typing import Literal

import fakeredis
import httpx
import pytest
import pytest_asyncio

from app.clients.fakes import fake_json
from app.core import llm_gate
from app.core.config import get_settings
from app.core.errors import LLMUnavailable, StructuredOutputError
from app.core.llm_gate import LLMGate
from app.schemas.llm import FlatModel, flat_json_schema
from app.services import ai_service, llm_provider
from app.services.llm_provider import (
    LLMConfig,
    capture,
    complete_messages,
    complete_structured,
    fake_llm_active,
    schema_prompt,
    stream_messages,
)
from tests.fixtures.fake_llm import KoboldSocketGuard


class Item(FlatModel):
    name: str
    count: int


class Report(FlatModel):
    kind: Literal["npc", "place", "item"]
    title: str
    items: list[Item]
    done: bool


VALID = '{"kind": "place", "title": "Mill", "items": [{"name": "rope", "count": 2}], "done": true}'
BAD = '{"kind": "place", "title": "Mill"}'
MESSAGES = [
    {"role": "system", "content": "You keep notes."},
    {"role": "user", "content": "What happened at the mill last night after the storm broke over the river?"},
]


def platform_cfg(**kwargs) -> LLMConfig:
    return LLMConfig(provider="kobold", api_url=get_settings().kobold_url, **kwargs)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch, fake_llm):
    monkeypatch.setattr(llm_provider, "_backend_cache", {})
    monkeypatch.setattr(llm_provider, "structured_stats", {})
    monkeypatch.setattr(llm_provider, "_transport", None)


@pytest_asyncio.fixture
async def gate(monkeypatch):
    redis = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    g = LLMGate(redis, capacity=1, wait_s=1, poll_s=0.01, key_prefix=f"test_gate:{uuid.uuid4().hex}")
    monkeypatch.setattr(llm_gate, "get_gate", lambda: g)
    yield g
    await redis.aclose()


CONFIGS = {
    "default": None,
    "openai": LLMConfig(provider="openai", api_key="sk-test"),
    "anthropic_no_key": LLMConfig(provider="anthropic"),
    "gemini": LLMConfig(provider="gemini", api_key="g-test"),
    "custom": LLMConfig(provider="custom", api_url="http://byok.test"),
}


# --- plain and stream ------------------------------------------------------


@pytest.mark.parametrize("name", list(CONFIGS))
async def test_plain_is_deterministic_per_messages(gate, name):
    cfg = CONFIGS[name]
    a = await complete_messages(MESSAGES, cfg)
    b = await complete_messages([dict(m) for m in MESSAGES], cfg)
    other = await complete_messages([{"role": "user", "content": "Something else"}], cfg)
    assert a == b != other
    assert a.startswith("[fake-llm ")
    assert a.endswith("] What happened at the mill last night after the storm broke over")  # 12 words


async def test_plain_differs_on_any_message_not_just_the_last_user_turn():
    cfg = LLMConfig(provider="fake")
    other = [{"role": "system", "content": "Different system."}, MESSAGES[1]]
    assert await complete_messages(MESSAGES, cfg) != await complete_messages(other, cfg)


@pytest.mark.parametrize("name", list(CONFIGS))
async def test_stream_chunks_join_to_the_complete_reply(gate, name):
    cfg = CONFIGS[name]
    chunks = [c async for c in stream_messages(MESSAGES, cfg)]
    assert len(chunks) >= 2
    assert "".join(chunks) == await complete_messages(MESSAGES, cfg)


async def test_stream_of_a_one_word_script_still_has_two_chunks(fake_llm):
    fake_llm.script(["hi"])
    chunks = [c async for c in stream_messages(MESSAGES, LLMConfig(provider="fake"))]
    assert len(chunks) >= 2 and "".join(chunks) == "hi"


async def test_platform_stream_holds_and_releases_a_slot(gate):
    async for _ in stream_messages(MESSAGES, platform_cfg()):
        assert await gate.redis.zcard(gate.holders_key) == 1
    assert await gate.redis.zcard(gate.holders_key) == 0


async def test_scripted_reply_is_returned_as_str(fake_llm):
    fake_llm.script(["first", 42])
    cfg = LLMConfig(provider="fake")
    assert await complete_messages(MESSAGES, cfg) == "first"
    assert await complete_messages(MESSAGES, cfg) == "42"
    assert (await complete_messages(MESSAGES, cfg)).startswith("[fake-llm ")


async def test_scripted_error_raised_by_plain_stream_and_structured(fake_llm):
    cfg = LLMConfig(provider="fake")
    fake_llm.script([LLMUnavailable("down"), LLMUnavailable("down"), LLMUnavailable("down")])
    with pytest.raises(LLMUnavailable):
        await complete_messages(MESSAGES, cfg)
    with pytest.raises(LLMUnavailable):
        async for _ in stream_messages(MESSAGES, cfg):
            pass
    with pytest.raises(LLMUnavailable):
        await complete_structured(MESSAGES, Report, cfg)
    assert fake_llm.pending == 0


# --- structured ------------------------------------------------------------


def test_fake_json_shapes():
    value = fake_json(flat_json_schema(Report))
    assert value == {"kind": "npc", "title": "fake", "items": [{"name": "fake", "count": 0}], "done": False}
    assert fake_json({"type": "integer", "minimum": 3}) == 3
    assert fake_json({"type": "number", "minimum": 0.5}) == 0.5
    assert fake_json({"const": "x"}) == "x"
    assert fake_json({"type": "array", "items": {"enum": [7, 8]}}) == [7]


async def test_structured_unscripted_is_a_minimal_valid_instance(gate, caplog):
    caplog.set_level(logging.INFO, logger="app.services.llm_provider")
    with capture() as cap:
        out = await complete_structured(MESSAGES, Report, platform_cfg(), task="fake_it")
    assert isinstance(out, Report)
    assert (out.kind, out.title, len(out.items), out.done) == ("npc", "fake", 1, False)
    assert llm_provider.structured_stats["fake_it"]["first_try_valid"] == 1
    line = json.loads(next(r.getMessage() for r in caplog.records if "structured_attempt" in r.getMessage()))
    assert line["backend"] == llm_provider.MODE_FAKE and line["valid"] is True
    (call,) = cap.calls
    assert call.fake and call.schema == "Report" and call.task == "fake_it"
    assert schema_prompt(Report) in call.messages[-1]["content"]


async def test_structured_fake_never_probes_the_backend(monkeypatch):
    async def probe(*_):
        raise AssertionError("detect_backend called")

    monkeypatch.setattr(llm_provider, "detect_backend", probe)
    assert isinstance(await complete_structured(MESSAGES, Report, LLMConfig(provider="openai")), Report)


async def test_scripted_repair(fake_llm):
    fake_llm.script([BAD, VALID])
    with capture() as cap:
        out = await complete_structured(MESSAGES, Report, LLMConfig(provider="fake"), task="rep")
    assert out.title == "Mill" and out.items[0].count == 2
    assert len(cap.calls) == 2
    first, second = cap.calls
    assert {"role": "assistant", "content": BAD} in second.messages
    assert second.messages[: len(first.messages)] == first.messages
    assert "did not match the JSON schema" in second.messages[-1]["content"]
    assert llm_provider.structured_stats["rep"] == {"first_try_valid": 0, "valid_after_repair": 1, "failed": 0}


async def test_scripted_exhausted(fake_llm):
    fake_llm.script([BAD] * 3)
    with capture() as cap:
        with pytest.raises(StructuredOutputError) as exc:
            await complete_structured(MESSAGES, Report, LLMConfig(provider="fake"))
    assert exc.value.attempts == 3
    assert len(cap.calls) == 3


# --- capture ---------------------------------------------------------------


async def test_capture_fields_platform(gate):
    with capture() as cap:
        await complete_messages(MESSAGES, platform_cfg(), task="recap", gate_class="live_recap")
        await complete_messages(MESSAGES, platform_cfg())
    a, b = cap.calls
    assert a.messages == MESSAGES and a.messages is not MESSAGES
    assert (a.task, a.gate_class, a.provider, a.fake, a.schema) == ("recap", "live_recap", "kobold", True, None)
    assert a.model == get_settings().local_llm_model
    assert b.gate_class == llm_gate.current_class.get().value


async def test_capture_fields_byok_and_models():
    configs = [
        (LLMConfig(provider="openai", api_key="sk-secret-1"), "gpt-4o-mini"),
        (LLMConfig(provider="anthropic", api_key="sk-secret-2"), llm_provider.ANTHROPIC_DEFAULT_MODEL),
        (LLMConfig(provider="gemini", api_key="sk-secret-3", model="gemini-x"), "gemini-x"),
        (LLMConfig(provider="custom", api_url="http://byok.test", api_key="sk-secret-4"), "local-model"),
    ]
    with capture() as cap:
        for cfg, _ in configs:
            await complete_messages(MESSAGES, cfg)
    assert [c.model for c in cap.calls] == [m for _, m in configs]
    assert all(c.gate_class is None for c in cap.calls)
    dumped = json.dumps([dataclasses.asdict(c) for c in cap.calls])
    assert "sk-secret" not in dumped and "api_key" not in dumped
    assert set(dataclasses.asdict(cap.calls[0])) == {
        "messages", "task", "gate_class", "model", "provider", "fake", "schema",
    }


async def test_capture_copies_messages():
    msgs = [{"role": "user", "content": "hello"}]
    with capture() as cap:
        await complete_messages(msgs, LLMConfig(provider="fake"))
    msgs[0]["content"] = "changed"
    assert cap.calls[0].messages == [{"role": "user", "content": "hello"}]


async def test_captures_nest():
    cfg = LLMConfig(provider="fake")
    with capture() as outer:
        await complete_messages([{"role": "user", "content": "one"}], cfg)
        with capture() as inner:
            await complete_messages([{"role": "user", "content": "two"}], cfg)
        await complete_messages([{"role": "user", "content": "three"}], cfg)
    await complete_messages([{"role": "user", "content": "four"}], cfg)
    assert [c.messages[0]["content"] for c in outer.calls] == ["one", "two", "three"]
    assert [c.messages[0]["content"] for c in inner.calls] == ["two"]


async def test_capture_off_does_no_record_work(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("record work with no capture active")

    monkeypatch.setattr(llm_provider, "_call_model", boom)
    monkeypatch.setattr(llm_provider, "CapturedCall", boom)
    cfg = LLMConfig(provider="fake")
    await complete_messages(MESSAGES, cfg)
    [c async for c in stream_messages(MESSAGES, cfg)]
    await complete_structured(MESSAGES, Report, cfg)


# --- MockTransport: the real senders, still captured -------------------------


def _serve(monkeypatch, replies):
    payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(await request.aread())
        payloads.append(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": replies.pop(0)}}]})

    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(handler))
    return payloads


async def test_mock_transport_turns_the_fake_off_and_capture_sees_the_wire(monkeypatch):
    payloads = _serve(monkeypatch, ["real reply"])
    cfg = LLMConfig(provider="custom", api_url="http://byok.test", model="m", api_key="sk-wire")
    assert not fake_llm_active(cfg)
    with capture() as cap:
        assert await complete_messages(MESSAGES, cfg) == "real reply"
    (call,) = cap.calls
    assert call.fake is False and call.model == payloads[0]["model"] == "m"
    assert call.messages == payloads[0]["messages"]
    assert "sk-wire" not in json.dumps(dataclasses.asdict(call))


async def test_mock_transport_structured_attempts_match_the_wire(monkeypatch):
    payloads = _serve(monkeypatch, [BAD, VALID])
    cfg = LLMConfig(provider="custom", api_url="http://byok.test", model="m")
    with capture() as cap:
        out = await complete_structured(MESSAGES, Report, cfg)
    assert out.title == "Mill"
    assert [c.messages for c in cap.calls] == [p["messages"] for p in payloads]
    assert all(c.fake is False and c.schema == "Report" for c in cap.calls)


# --- ai_service, backend detection, no socket --------------------------------


async def test_generate_narrative_under_the_fake_opens_no_socket(gate, no_kobold_socket):
    with capture() as cap:
        text = await ai_service.generate_narrative("party fought goblins at the mill")
    assert text.startswith("[fake-llm ")
    (call,) = cap.calls
    assert call.task == "narrative" and call.fake
    assert no_kobold_socket.hits == []


async def test_detect_backend_short_circuits_under_the_fake(no_kobold_socket):
    assert await llm_provider.detect_backend(None) == llm_provider.BACKEND_OLLAMA
    assert llm_provider._backend_cache == {}
    assert no_kobold_socket.hits == []


# --- fake_llm_active ----------------------------------------------------------


def test_fake_llm_active_in_test_env_and_opt_outs(monkeypatch):
    kobold, fake = platform_cfg(), LLMConfig(provider="fake")
    assert fake_llm_active(kobold) and fake_llm_active(fake)

    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(lambda r: httpx.Response(200)))
    assert not fake_llm_active(kobold) and fake_llm_active(fake)
    monkeypatch.setattr(llm_provider, "_transport", None)

    monkeypatch.setattr(llm_provider, "_real_llm_in_test", True)
    assert not fake_llm_active(kobold) and fake_llm_active(fake)
    monkeypatch.setattr(llm_provider, "_real_llm_in_test", False)


def test_fake_llm_active_in_production(monkeypatch):
    prod = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(llm_provider, "get_settings", lambda: prod)
    assert not fake_llm_active(platform_cfg())
    assert not fake_llm_active(LLMConfig(provider="openai", api_key="k"))
    assert fake_llm_active(LLMConfig(provider="fake"))


async def test_fake_provider_in_production_is_ungated(monkeypatch):
    prod = get_settings().model_copy(update={"environment": "production"})
    monkeypatch.setattr(llm_provider, "get_settings", lambda: prod)

    def touched():
        raise AssertionError("the fake provider reached the gate")

    monkeypatch.setattr(llm_gate, "get_gate", touched)
    assert (await complete_messages(MESSAGES, LLMConfig(provider="fake"))).startswith("[fake-llm ")


@pytest.mark.ollama
def test_ollama_marker_turns_the_fake_and_guard_off(no_kobold_socket):
    import _socket

    assert no_kobold_socket is None
    assert llm_provider._real_llm_in_test is True
    assert not fake_llm_active(platform_cfg())
    assert socket.socket.connect is _socket.socket.connect  # not patched


# --- the guard ------------------------------------------------------------------


def test_guard_refuses_and_records_kobold_connects(no_kobold_socket):
    guard = no_kobold_socket
    target = sorted(guard.targets)[0]
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(OSError):
            s.connect(target)
        assert s.connect_ex(target) == errno.ECONNREFUSED
    finally:
        s.close()
    assert guard.hits == [target, target]
    with pytest.raises(pytest.fail.Exception, match="KOBOLD_URL"):
        guard.verify()
    guard.hits.clear()  # the planted connects must not fail this test


def test_guard_lets_other_sockets_through(no_kobold_socket):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    if ("127.0.0.1", port) in no_kobold_socket.targets:
        pytest.skip("the ephemeral port is KOBOLD_URL's")
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(("127.0.0.1", port))
    finally:
        client.close()
        server.close()
    assert no_kobold_socket.hits == []


def test_guard_resolves_kobold_url():
    guard = KoboldSocketGuard("http://localhost:5001")
    assert ("localhost", 5001) in guard.targets
    assert ("127.0.0.1", 5001) in guard.targets or ("::1", 5001) in guard.targets
    assert KoboldSocketGuard("https://llm.invalid").targets == {("llm.invalid", 443)}


# --- scripted item types ----------------------------------------------------------


async def test_scripted_items_are_serialised_by_type(fake_llm):
    cfg = LLMConfig(provider="fake")
    fake_llm.script([
        {"a": 1},
        [1, "x"],
        Report.model_validate_json(VALID),
        "plain",
    ])
    assert json.loads(await complete_messages(MESSAGES, cfg)) == {"a": 1}
    assert json.loads(await complete_messages(MESSAGES, cfg)) == [1, "x"]
    assert Report.model_validate_json(await complete_messages(MESSAGES, cfg)).title == "Mill"
    assert await complete_messages(MESSAGES, cfg) == "plain"


async def test_scripted_dict_validates_in_structured(fake_llm):
    fake_llm.script([json.loads(VALID)])
    out = await complete_structured(MESSAGES, Report, LLMConfig(provider="fake"))
    assert out.title == "Mill"


async def test_scripted_exception_class_is_raised(fake_llm):
    fake_llm.script([RuntimeError])
    with pytest.raises(RuntimeError):
        await complete_messages(MESSAGES, LLMConfig(provider="fake"))


# --- fake_json against real schemas and constraints ----------------------------------


def _all_flat_models():
    import importlib
    import inspect
    import pkgutil

    import app.schemas.llm as llm_schemas

    modules = [llm_schemas] + [
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(llm_schemas.__path__, prefix=f"{llm_schemas.__name__}.")
    ]
    found = {}
    for module in modules:
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, FlatModel) and obj is not FlatModel and obj.__module__ == module.__name__:
                found[f"{obj.__module__}.{obj.__qualname__}"] = obj
    return [found[k] for k in sorted(found)]


@pytest.mark.parametrize(
    "model", _all_flat_models() or [pytest.param(None, marks=pytest.mark.skip("no feature schemas yet"))]
)
def test_fake_json_validates_every_llm_schema(model):
    model.model_validate(fake_json(flat_json_schema(model)))


def test_fake_json_honours_constraint_keywords():
    from typing import Annotated

    from pydantic import Field

    class Constrained(FlatModel):
        score: Annotated[int, Field(ge=2, le=9)]
        negative: Annotated[int, Field(le=-3)]
        below: Annotated[float, Field(lt=-1)]
        ratio: Annotated[float, Field(gt=0.25)]
        code: Annotated[str, Field(min_length=6, max_length=8)]
        short: Annotated[str, Field(max_length=2)]
        tags: Annotated[list[str], Field(min_length=3)]
        none: Annotated[list[str], Field(max_length=0)]

    value = fake_json(flat_json_schema(Constrained))
    assert value["score"] == 2 and value["negative"] == -3 and value["below"] < -1
    assert len(value["code"]) == 6 and value["short"] == "fa"
    assert len(value["tags"]) == 3 and value["none"] == []
    Constrained.model_validate(value)
    assert fake_json({"type": "integer", "minimum": 2.1}) == 3


# --- streams and the KoboldCpp-native attempt are captured ------------------------------


async def test_fake_stream_is_captured():
    with capture() as cap:
        [c async for c in stream_messages(MESSAGES, LLMConfig(provider="fake"), task="chat")]
    (call,) = cap.calls
    assert call.messages == MESSAGES and call.task == "chat" and call.fake is True


async def test_mock_transport_stream_is_captured_as_sent(monkeypatch):
    payloads: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(await request.aread()))
        body = ('data: {"choices": [{"delta": {"content": "hi "}}]}\n\n'
                'data: {"choices": [{"delta": {"content": "there"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(handler))
    cfg = LLMConfig(provider="custom", api_url="http://byok.test", model="m")
    with capture() as cap:
        chunks = [c async for c in stream_messages(MESSAGES, cfg)]
    assert "".join(chunks) == "hi there"
    (call,) = cap.calls
    assert call.messages == payloads[0]["messages"] and call.fake is False and call.model == "m"


async def test_kobold_native_narrative_prompt_is_captured(gate, monkeypatch):
    sent: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(404, text="not found")
        assert request.url.path == "/api/v1/generate"
        sent.append(json.loads(await request.aread())["prompt"])
        return httpx.Response(200, json={"results": [{"text": "native text"}]})

    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(handler))
    with capture() as cap:
        assert await ai_service.generate_narrative("party fought goblins") == "native text"
    (call,) = cap.calls
    assert call.messages == [{"role": "user", "content": sent[0]}]
    assert call.task == "narrative" and call.fake is False and call.provider == "kobold"
    assert call.gate_class == llm_gate.current_class.get().value
