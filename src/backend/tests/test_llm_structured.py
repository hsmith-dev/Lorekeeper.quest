"""E0-LLM.4: llm_provider.complete_structured.

Every backend is an httpx.MockTransport on llm_provider._transport and the
gate is a fakeredis-backed LLMGate swapped in for llm_gate.get_gate, so no
test opens a socket to KOBOLD_URL or needs a Redis server.
"""

import json
import logging
import re
import uuid
from types import SimpleNamespace

import fakeredis
import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import BaseModel, field_validator

from app.core import llm_gate
from app.core.config import get_settings
from app.core.errors import (
    LLMBusy,
    LLMConfigError,
    LLMUnavailable,
    PromptBudgetError,
    StructuredOutputError,
)
from app.core.llm_gate import GateClass, LLMGate
from app.schemas.llm import FlatModel, flat_json_schema
from app.services import llm_provider, prompt_budget
from app.services.llm_provider import LLMConfig, complete_structured, schema_prompt


class Entity(FlatModel):
    name: str
    type: str


class Extraction(FlatModel):
    entities: list[Entity]

    @field_validator("entities")
    @classmethod
    def at_least_one(cls, v):
        if not v:
            raise ValueError("at least one entity is required")
        return v


VALID = '{"entities": [{"name": "Mira", "type": "npc"}]}'
BAD = '{"entities": [{"name": "Mira"}]}'           # missing "type"
BAD2 = '{"entities": [{"name": "Mira", "type": 3}]}'  # wrong type
MESSAGES = [
    {"role": "system", "content": "You extract entities."},
    {"role": "user", "content": "Mira the innkeeper greeted us."},
]


def platform_cfg(**kwargs) -> LLMConfig:
    return LLMConfig(provider="kobold", api_url=get_settings().kobold_url, **kwargs)


# --- fakes -----------------------------------------------------------------


class Server:
    """Ollama (/api/version, /api/chat) or KoboldCpp (/api/version 404s),
    plus OpenAI, Anthropic and Gemini endpoints. Each chat request takes the
    next scripted reply. `fail(request)` may return a Response (or raise)
    instead; `reject_format` 400s any request carrying response_format."""

    def __init__(self, replies, *, ollama: bool = True):
        self.replies = list(replies)
        self.ollama = ollama
        self.version_calls = 0
        self.chats: list[SimpleNamespace] = []
        self.fail = None
        self.reject_format = False

    @property
    def payloads(self) -> list[dict]:
        return [c.payload for c in self.chats]

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            self.version_calls += 1
            if self.ollama:
                return httpx.Response(200, json={"version": "0.4.3"})
            return httpx.Response(404, text="404 page not found")
        payload = json.loads(await request.aread())
        self.chats.append(SimpleNamespace(
            host=request.url.host, path=request.url.path, payload=payload, headers=request.headers,
        ))
        if self.fail is not None:
            return self.fail(request)
        if self.reject_format and "response_format" in payload:
            return httpx.Response(400, json={"error": "response_format not supported"})
        reply = self.replies.pop(0)
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"message": {"role": "assistant", "content": reply}, "done": True})
        if request.url.host == "api.anthropic.com":
            return httpx.Response(200, json={"content": [{"type": "text", "text": reply}]})
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": reply}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(llm_provider, "_backend_cache", {})
    monkeypatch.setattr(llm_provider, "structured_stats", {})


@pytest.fixture
def serve(monkeypatch):
    def make(replies=(), *, ollama: bool = True) -> Server:
        s = Server(replies, ollama=ollama)
        monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(s.handler))
        return s

    return make


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


def stats(task="structured") -> dict:
    return llm_provider.structured_stats.get(task, {"first_try_valid": 0, "valid_after_repair": 0, "failed": 0})


# --- the happy path, Ollama ------------------------------------------------


async def test_valid_first_try_ollama(serve, gate):
    server = serve([VALID])
    original = json.loads(json.dumps(MESSAGES))
    result = await complete_structured(MESSAGES, Extraction, platform_cfg())

    assert isinstance(result, Extraction)
    assert result.entities[0].name == "Mira"
    assert len(server.chats) == 1
    chat = server.chats[0]
    assert chat.path == "/api/chat"
    p = chat.payload
    assert p["format"] == flat_json_schema(Extraction)
    assert p["stream"] is False
    assert p["options"] == {"temperature": 0, "num_predict": prompt_budget.TASK_POLICIES["structured"].reserved_output}
    assert p["model"] == get_settings().local_llm_model
    # The schema is restated in the final user turn of a copy.
    assert p["messages"][0] == MESSAGES[0]
    assert p["messages"][-1]["role"] == "user"
    assert p["messages"][-1]["content"] == MESSAGES[1]["content"] + "\n\n" + schema_prompt(Extraction)
    assert len(p["messages"]) == 2
    assert MESSAGES == original  # caller's list untouched

    assert stats() == {"first_try_valid": 1, "valid_after_repair": 0, "failed": 0}
    assert gate.acquired == [GateClass.gm_interactive]
    assert await gate.holder_count() == 0


async def test_schema_added_as_new_user_turn(serve, gate):
    server = serve([VALID])
    msgs = [*MESSAGES, {"role": "assistant", "content": "Noted."}]
    await complete_structured(msgs, Extraction, platform_cfg())
    sent = server.payloads[0]["messages"]
    assert sent[:3] == msgs
    assert sent[3] == {"role": "user", "content": schema_prompt(Extraction)}
    assert len(msgs) == 3


def test_schema_prompt_has_schema_and_instruction():
    text = schema_prompt(Extraction)
    assert "only one JSON object" in text
    assert json.dumps(flat_json_schema(Extraction), separators=(",", ":")) in text


# --- repairs -----------------------------------------------------------------


async def test_repair_on_turn_one(serve, gate):
    server = serve([BAD, VALID])
    result = await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert result.entities[0].type == "npc"
    assert len(server.chats) == 2
    first, second = server.payloads[0]["messages"], server.payloads[1]["messages"]
    assert second[: len(first)] == first
    assert second[len(first)] == {"role": "assistant", "content": BAD}
    repair = second[len(first) + 1]
    assert repair["role"] == "user"
    assert "entities.0.type: Field required" in repair["content"]
    assert "corrected JSON" in repair["content"]
    assert len(second) == len(first) + 2
    assert server.payloads[1]["format"] == flat_json_schema(Extraction)
    assert stats() == {"first_try_valid": 0, "valid_after_repair": 1, "failed": 0}


async def test_repair_on_turn_two_echoes_only_latest(serve, gate):
    server = serve([BAD, BAD2, VALID])
    result = await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert isinstance(result, Extraction)
    assert len(server.chats) == 3
    third = server.payloads[2]["messages"]
    assert len(third) == len(server.payloads[0]["messages"]) + 2
    assert third[-2] == {"role": "assistant", "content": BAD2}
    assert BAD not in json.dumps(third)
    assert stats()["valid_after_repair"] == 1
    assert gate.acquired == [GateClass.gm_interactive]  # one slot for all three


async def test_exhausted_raises_structured_output_error(serve, gate):
    server = serve([BAD, BAD, BAD2])
    with pytest.raises(StructuredOutputError) as exc_info:
        await complete_structured(MESSAGES, Extraction, platform_cfg())
    err = exc_info.value
    assert err.code == "ai_output_unusable"
    assert err.status_code == 422
    assert err.attempts == 3
    assert err.errors and set(err.errors[0]) == {"loc", "msg", "type"}
    assert err.errors[0]["loc"] == "entities.0.type"
    json.dumps(err.errors)  # JSON-safe
    assert len(server.chats) == 3
    assert stats() == {"first_try_valid": 0, "valid_after_repair": 0, "failed": 1}
    assert gate.acquired == [GateClass.gm_interactive]
    assert await gate.holder_count() == 0


@pytest.mark.parametrize(
    "bad",
    [
        '{"entities": [',                                   # malformed JSON
        '{"entities": []}',                                 # semantically empty (validator)
        "{}",                                               # missing everything
        '{"entities": [{"name": "M", "type": "npc"}], "x": 1}',  # extra key
        '{"entities": [{"name": "M", "type": "npc", "x": 1}]}',  # extra nested key
        "No entities here.",                                # no JSON at all
    ],
    ids=["malformed", "empty", "missing", "extra", "extra-nested", "prose"],
)
async def test_invalid_outputs_are_repaired(serve, gate, bad):
    server = serve([bad, VALID])
    result = await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert isinstance(result, Extraction)
    assert len(server.chats) == 2
    assert server.payloads[1]["messages"][-2] == {"role": "assistant", "content": bad}


async def test_semantic_validator_message_reaches_repair(serve, gate):
    server = serve(['{"entities": []}', VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert "at least one entity is required" in server.payloads[1]["messages"][-1]["content"]


@pytest.mark.parametrize(
    "reply",
    [
        f"```json\n{VALID}\n```",
        f"```json {VALID}```",
        f"```\n{VALID}\n```",
        f"Here: {VALID}",
        f"Sure! Here is the JSON:\n```json\n{VALID}\n```\nHope that helps.",
    ],
    ids=["fence", "inline-fence", "bare-fence", "chatty", "chatty-fence"],
)
async def test_fenced_and_chatty_replies_parse(serve, gate, reply):
    server = serve([reply])
    result = await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert result.entities[0].name == "Mira"
    assert len(server.chats) == 1


async def test_repair_errors_truncated(serve, gate):
    many_bad = json.dumps({"entities": [{"name": f"n{i}"} for i in range(200)]})
    server = serve([many_bad, VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg())
    repair = server.payloads[1]["messages"][-1]["content"]
    errors_part = repair.split("Validation errors:\n", 1)[1].split("\n\nReply with only", 1)[0]
    assert len(errors_part) <= llm_provider.REPAIR_ERRORS_MAX_CHARS
    assert errors_part.startswith("entities.0.type: Field required")


# --- repair prompt and the budget --------------------------------------------


def _filler_for(tokens: int) -> str:
    """Text whose estimate is about `tokens`."""
    return "word " * int(tokens / prompt_budget.SAFETY_MARGIN * prompt_budget.CHARS_PER_TOKEN / 5)


async def test_repair_prompt_shortens_echo_to_fit(serve, gate):
    window = prompt_budget.window_tokens("structured")
    base_tokens = prompt_budget.estimate_messages(
        llm_provider._with_schema(MESSAGES, schema_prompt(Extraction))
    )
    msgs = [MESSAGES[0], {"role": "user", "content": _filler_for(window - base_tokens - 300)}]
    huge_bad = '{"entities": [' + ", ".join(['{"name": "x"}'] * 400)  # malformed and long
    server = serve([huge_bad, VALID])
    await complete_structured(msgs, Extraction, platform_cfg())
    repair = server.payloads[1]["messages"]
    assert prompt_budget.estimate_messages(server.payloads[0]["messages"]) <= window
    assert prompt_budget.estimate_messages(repair) <= window
    echoed = repair[-2]
    assert echoed["role"] == "assistant"
    assert echoed["content"].endswith("...")
    assert huge_bad.startswith(echoed["content"][:-3])
    assert len(echoed["content"]) < len(huge_bad)


async def test_repair_prompt_drops_echo_when_nothing_fits(serve, gate):
    window = prompt_budget.window_tokens("structured")
    bad = '{"entities": ['
    _, errors = llm_provider._validate(bad, Extraction)
    ask = llm_provider._repair_messages([], bad, errors, None)[-1]
    ask_tokens = prompt_budget.estimate_messages([ask]) + 5  # + " (not shown)"
    # Grow the prompt until the errors turn just fits but an echo turn
    # (>= 8 tokens with its template overhead) can't fit as well.
    content = MESSAGES[1]["content"]
    while True:
        msgs = [MESSAGES[0], {"role": "user", "content": content}]
        first_tokens = prompt_budget.estimate_messages(llm_provider._with_schema(msgs, schema_prompt(Extraction)))
        if first_tokens >= window - ask_tokens - 2:
            break
        content += "w" if window - ask_tokens - first_tokens < 20 else " word" * 10
    assert first_tokens <= window - ask_tokens
    server = serve([bad, VALID])
    await complete_structured(msgs, Extraction, platform_cfg())
    repair = server.payloads[1]["messages"]
    assert prompt_budget.estimate_messages(repair) <= window
    assert [m["role"] for m in repair[-2:]] == ["user", "user"]
    assert "(not shown)" in repair[-1]["content"]


async def test_repair_over_window_is_unusable(serve, gate):
    window = prompt_budget.window_tokens("structured")
    # The first prompt just fits; base + any errors turn can't.
    content = MESSAGES[1]["content"]
    while True:
        msgs = [MESSAGES[0], {"role": "user", "content": content}]
        first_tokens = prompt_budget.estimate_messages(llm_provider._with_schema(msgs, schema_prompt(Extraction)))
        if first_tokens >= window - 3:
            break
        content += "w" if window - first_tokens < 20 else " word" * 10
    assert first_tokens <= window
    server = serve(['{"entities": [', VALID])
    with pytest.raises(StructuredOutputError) as exc_info:
        await complete_structured(msgs, Extraction, platform_cfg())
    assert exc_info.value.attempts == 1
    assert exc_info.value.errors
    assert len(server.chats) == 1
    assert await gate.holder_count() == 0
    assert llm_provider.structured_stats["structured"]["failed"] == 1


def test_repair_messages_unbounded_for_byok():
    base = [{"role": "user", "content": "x" * 50000}]
    out = llm_provider._repair_messages(base, "y" * 50000, [{"loc": "a", "msg": "b", "type": "c"}], None)
    assert out[-2] == {"role": "assistant", "content": "y" * 50000}


async def test_too_big_raises_before_any_request(serve, gate):
    server = serve([VALID])
    window = prompt_budget.window_tokens("structured")
    msgs = [{"role": "user", "content": _filler_for(window + 100)}]
    with pytest.raises(PromptBudgetError):
        await complete_structured(msgs, Extraction, platform_cfg())
    assert server.chats == [] and server.version_calls == 0
    assert gate.acquired == []


async def test_budget_uses_task_policy(serve, gate):
    # live_recap reserves less output, so its window is larger than "structured".
    s_window = prompt_budget.window_tokens("structured")
    msgs = [{"role": "user", "content": _filler_for(s_window + 100)}]
    with pytest.raises(PromptBudgetError):
        await complete_structured(msgs, Extraction, platform_cfg(), task="zz_unknown_task")
    server = serve([VALID])
    await complete_structured(msgs, Extraction, platform_cfg(), task="live_recap")
    assert server.payloads[0]["options"]["num_predict"] == prompt_budget.TASK_POLICIES["live_recap"].reserved_output


async def test_byok_skips_budget(serve, no_gate):
    server = serve([VALID])
    window = prompt_budget.window_tokens("structured")
    msgs = [{"role": "user", "content": _filler_for(window + 100)}]
    await complete_structured(msgs, Extraction, LLMConfig(provider="openai", api_key="sk-test"))
    assert len(server.chats) == 1


async def test_large_max_tokens_shrinks_window(serve, gate):
    server = serve([VALID])
    window = prompt_budget.window_tokens("structured")
    msgs = [{"role": "user", "content": _filler_for(window - 500)}]  # fits the default reserve
    with pytest.raises(PromptBudgetError):
        await complete_structured(msgs, Extraction, platform_cfg(), max_tokens=2048)
    assert server.chats == [] and server.version_calls == 0
    await complete_structured(msgs, Extraction, platform_cfg())
    assert len(server.chats) == 1


async def test_explicit_max_tokens(serve, gate):
    server = serve([VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg(), max_tokens=77)
    assert server.payloads[0]["options"]["num_predict"] == 77


# --- KoboldCpp / OpenAI-compatible ------------------------------------------


async def test_koboldcpp_strict_response_format(serve, gate):
    server = serve([VALID], ollama=False)
    await complete_structured(MESSAGES, Extraction, platform_cfg(), task="extraction")
    chat = server.chats[0]
    assert chat.path == "/v1/chat/completions"
    p = chat.payload
    assert p["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "extraction", "schema": flat_json_schema(Extraction), "strict": True},
    }
    assert p["temperature"] == 0
    assert p["stream"] is False
    assert p["model"] == get_settings().local_llm_model
    assert p["messages"][-1]["content"].endswith(schema_prompt(Extraction))


async def test_koboldcpp_4xx_falls_back_to_prompted_and_stays(serve, gate):
    server = serve([BAD, VALID], ollama=False)
    server.reject_format = True
    result = await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert isinstance(result, Extraction)
    has_format = ["response_format" in p for p in server.payloads]
    assert has_format == [True, False, False]  # rejected, prompted retry, prompted repair
    assert server.payloads[1]["messages"] == server.payloads[0]["messages"]
    assert server.payloads[1]["temperature"] == 0
    assert server.payloads[2]["messages"][-2] == {"role": "assistant", "content": BAD}
    assert stats() == {"first_try_valid": 0, "valid_after_repair": 1, "failed": 0}
    assert gate.acquired == [GateClass.gm_interactive]


async def test_byok_openai_strict_and_gate_untouched(serve, no_gate):
    server = serve([VALID])
    result = await complete_structured(MESSAGES, Extraction, LLMConfig(provider="openai", api_key="sk-test"))
    assert isinstance(result, Extraction)
    assert server.version_calls == 0
    chat = server.chats[0]
    assert chat.host == "api.openai.com"
    assert chat.headers["authorization"] == "Bearer sk-test"
    assert chat.payload["response_format"]["json_schema"]["strict"] is True
    assert chat.payload["model"] == "gpt-4o-mini"


async def test_byok_custom_and_own_kobold_bypass_gate(serve, no_gate):
    server = serve([VALID, VALID])
    await complete_structured(MESSAGES, Extraction, LLMConfig(provider="custom", api_url="http://custom.test:8000"))
    await complete_structured(
        MESSAGES, Extraction, LLMConfig(provider="kobold", api_url="http://own.test:11434", model="mine"),
    )
    assert server.chats[0].payload["response_format"]["type"] == "json_schema"
    assert server.chats[1].path == "/api/chat"  # own Ollama detected
    assert server.chats[1].payload["model"] == "mine"


# --- prompted providers -------------------------------------------------------


async def test_anthropic_prompted(serve, no_gate):
    server = serve([f"Here you go:\n{VALID}"])
    result = await complete_structured(MESSAGES, Extraction, LLMConfig(provider="anthropic", api_key="k"))
    assert isinstance(result, Extraction)
    p = server.chats[0].payload
    assert server.chats[0].host == "api.anthropic.com"
    assert p["temperature"] == 0
    assert p["system"] == MESSAGES[0]["content"]
    assert p["messages"][-1]["role"] == "user"
    assert p["messages"][-1]["content"].endswith(schema_prompt(Extraction))
    assert "response_format" not in p and "format" not in p


async def test_gemini_prompted_with_repair(serve, no_gate):
    server = serve([BAD, VALID])
    await complete_structured(MESSAGES, Extraction, LLMConfig(provider="gemini", api_key="k"))
    first, second = server.payloads
    assert server.chats[0].host == "generativelanguage.googleapis.com"
    assert first["generationConfig"]["temperature"] == 0
    assert first["contents"][-1]["parts"][0]["text"].endswith(schema_prompt(Extraction))
    assert [c["role"] for c in second["contents"]] == ["user", "model", "user"]
    assert second["contents"][1]["parts"][0]["text"] == BAD


@pytest.mark.parametrize("provider", ["anthropic", "gemini"])
async def test_missing_byok_key_is_config_error(serve, no_gate, provider):
    server = serve([VALID])
    with pytest.raises(LLMConfigError):
        await complete_structured(MESSAGES, Extraction, LLMConfig(provider=provider))
    assert server.chats == []
    assert llm_provider.structured_stats == {}


# --- backend failures ----------------------------------------------------------


def _status(code):
    return lambda request: httpx.Response(code, json={"error": "nope"})


def _refuse(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    "ollama,fail",
    [
        (True, _status(500)),
        (True, _status(404)),
        (True, _refuse),
        (True, lambda r: httpx.Response(200, json={"message": {"role": "assistant", "content": ""}})),
        (True, lambda r: httpx.Response(200, text="")),
        (False, _status(503)),
        (False, _refuse),
        (False, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": None}}]})),
        (False, lambda r: httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})),
    ],
    ids=[
        "ollama-5xx", "ollama-4xx", "ollama-refused", "ollama-empty", "ollama-no-body",
        "kobold-5xx", "kobold-refused", "kobold-null", "kobold-empty",
    ],
)
async def test_backend_down_is_unavailable(serve, gate, ollama, fail):
    server = serve([], ollama=ollama)
    server.fail = fail
    with pytest.raises(LLMUnavailable):
        await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert len(server.chats) == 1  # no repair, no prompted retry
    assert llm_provider.structured_stats == {}
    assert await gate.holder_count() == 0


async def test_4xx_on_prompted_path_is_unavailable(serve, gate):
    server = serve([], ollama=False)
    server.fail = _status(400)
    with pytest.raises(LLMUnavailable):
        await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert ["response_format" in p for p in server.payloads] == [True, False]


@pytest.mark.parametrize("provider", ["custom", "other"])
async def test_prompted_null_content_is_unavailable(serve, no_gate, provider):
    """custom: strict 400, then a prompted null; other: prompted from the start."""
    server = serve([])

    def null_when_prompted(request):
        if "response_format" in json.loads(request.content):
            return httpx.Response(400, json={"error": "no response_format"})
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    server.fail = null_when_prompted
    with pytest.raises(LLMUnavailable):
        await complete_structured(MESSAGES, Extraction, LLMConfig(provider=provider, api_url="http://custom.test:8000"))
    assert "response_format" not in server.payloads[-1]
    assert len(server.chats) == (2 if provider == "custom" else 1)
    assert llm_provider.structured_stats == {}


@pytest.mark.parametrize("task", ["live recap.v2", "t" * 70 + "!x"], ids=["punctuation", "long"])
async def test_json_schema_name_sanitised(serve, gate, task):
    server = serve([VALID], ollama=False)
    await complete_structured(MESSAGES, Extraction, platform_cfg(), task=task)
    name = server.payloads[0]["response_format"]["json_schema"]["name"]
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name)


@pytest.mark.parametrize("fail", [_status(401), _refuse], ids=["401", "refused"])
async def test_anthropic_failures_are_unavailable(serve, no_gate, fail):
    server = serve([])
    server.fail = fail
    with pytest.raises(LLMUnavailable):
        await complete_structured(MESSAGES, Extraction, LLMConfig(provider="anthropic", api_key="k"))
    assert len(server.chats) == 1


async def test_unavailable_mid_repair_propagates(serve, gate):
    server = serve([])
    calls = {"n": 0}

    def bad_then_502(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"message": {"role": "assistant", "content": BAD}})
        return httpx.Response(502)

    server.fail = bad_then_502
    with pytest.raises(LLMUnavailable):
        await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert len(server.chats) == 2  # the first call and the repair turn that hit the 502
    assert llm_provider.structured_stats == {}
    assert await gate.holder_count() == 0


# --- the gate --------------------------------------------------------------------


async def test_gate_one_acquire_chosen_class_released_on_success(serve, gate):
    serve([BAD, BAD2, VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg(), gate_class=GateClass.live_recap)
    assert gate.acquired == [GateClass.live_recap]
    assert await gate.holder_count() == 0


async def test_gate_released_after_failure(serve, gate):
    serve([BAD, BAD, BAD])
    with pytest.raises(StructuredOutputError):
        await complete_structured(MESSAGES, Extraction, platform_cfg(), gate_class="job_backfill")
    assert gate.acquired == [GateClass.job_backfill]
    assert await gate.holder_count() == 0


async def test_gate_current_class_default(serve, gate):
    serve([VALID])
    token = llm_gate.current_class.set(GateClass.job_onsave)
    try:
        await complete_structured(MESSAGES, Extraction, platform_cfg())
    finally:
        llm_gate.current_class.reset(token)
    assert gate.acquired == [GateClass.job_onsave]


async def test_busy_gate_sends_no_request(serve, gate):
    server = serve([VALID])
    held = await gate.acquire(GateClass.live_recap)
    try:
        token = llm_gate.current_deadline.set(0.0)  # already expired
        try:
            with pytest.raises(LLMBusy):
                await complete_structured(MESSAGES, Extraction, platform_cfg())
        finally:
            llm_gate.current_deadline.reset(token)
    finally:
        await held.release()
    assert server.chats == []
    assert server.version_calls == 1  # detect_backend ran before the slot


async def test_outer_slot_is_reused(serve, gate):
    serve([BAD, VALID])
    async with llm_gate.llm_slot(GateClass.live_recap):
        await complete_structured(MESSAGES, Extraction, platform_cfg())
    assert gate.acquired == [GateClass.live_recap]


# --- schema checks -------------------------------------------------------------


class Loose(BaseModel):  # not forbid
    name: str


class WithOptional(FlatModel):
    name: str | None


class WithDefault(FlatModel):
    name: str = ""


class NestedLoose(FlatModel):
    item: Loose


@pytest.mark.parametrize("schema", [Loose, WithOptional, WithDefault, NestedLoose])
async def test_non_flat_schema_rejected_before_request(serve, gate, schema):
    server = serve([VALID])
    with pytest.raises(ValueError, match="not a flat LLM schema"):
        await complete_structured(MESSAGES, schema, platform_cfg())
    assert server.chats == [] and server.version_calls == 0
    assert gate.acquired == []


# --- logging and stats -----------------------------------------------------------


async def test_attempt_log_lines(serve, gate, caplog):
    caplog.set_level(logging.INFO, logger="app.services.llm_provider")
    serve([BAD, VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg(), task="extraction")
    lines = []
    for rec in caplog.records:
        try:
            body = json.loads(rec.getMessage())
        except ValueError:
            continue
        if body.get("event") == "structured_attempt":
            lines.append(body)
    assert [ln["attempt"] for ln in lines] == [1, 2]
    assert [ln["valid"] for ln in lines] == [False, True]
    assert lines[0]["errors"] == [{"loc": "entities.0.type", "type": "missing"}]
    assert "errors" not in lines[1]
    for ln in lines:
        assert set(ln) - {"errors"} == {"event", "task", "attempt", "valid", "backend", "ms"}
        assert ln["task"] == "extraction"
        assert ln["backend"] == "ollama"
        assert isinstance(ln["ms"], int)
    assert "Mira" not in caplog.text  # never message or output text
    assert "Field required" not in caplog.text  # nor validation msgs
    assert llm_provider.structured_stats == {
        "extraction": {"first_try_valid": 0, "valid_after_repair": 1, "failed": 0},
    }


async def test_attempt_log_caps_errors(serve, gate, caplog):
    caplog.set_level(logging.INFO, logger="app.services.llm_provider")
    serve([json.dumps({"entities": [{"name": f"n{i}"} for i in range(30)]}), VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg())
    first = next(
        json.loads(r.getMessage()) for r in caplog.records if '"structured_attempt"' in r.getMessage()
    )
    assert len(first["errors"]) == llm_provider.LOG_ERRORS_MAX


async def test_stats_accumulate_per_task(serve, gate):
    serve([VALID, BAD, VALID, BAD, BAD, BAD, VALID])
    await complete_structured(MESSAGES, Extraction, platform_cfg(), task="a")
    await complete_structured(MESSAGES, Extraction, platform_cfg(), task="a")
    with pytest.raises(StructuredOutputError):
        await complete_structured(MESSAGES, Extraction, platform_cfg(), task="a")
    await complete_structured(MESSAGES, Extraction, platform_cfg(), task="b")
    assert llm_provider.structured_stats == {
        "a": {"first_try_valid": 1, "valid_after_repair": 1, "failed": 1},
        "b": {"first_try_valid": 1, "valid_after_repair": 0, "failed": 0},
    }


# --- a sample handler writes nothing when the output is unusable ---------------------


class PromoSuggestion(FlatModel):
    code: str
    note: str


async def sample_handler(db, cfg: LLMConfig, code: str) -> None:
    """What an AI route/Job looks like: ask, then write the result."""
    from app.db.models.promo_code import PromoCode

    suggestion = await complete_structured(
        [{"role": "user", "content": "Suggest a promo note."}], PromoSuggestion, cfg,
    )
    db.add(PromoCode(code=code, note=suggestion.note[:200], active=True))
    await db.flush()


async def test_sample_handler_writes_nothing_when_unusable(serve, gate, db):
    from app.db.models.promo_code import PromoCode

    good_code, bad_code = f"LLM4OK{uuid.uuid4().hex[:10]}", f"LLM4BAD{uuid.uuid4().hex[:10]}"
    serve(['{"code": "X", "note": "for testers"}', "{}", '{"code": 1}', "not json"])
    await sample_handler(db, platform_cfg(), good_code)
    with pytest.raises(StructuredOutputError):
        await sample_handler(db, platform_cfg(), bad_code)
    assert await db.scalar(sa.select(PromoCode).where(PromoCode.code == good_code)) is not None
    assert await db.scalar(sa.select(PromoCode).where(PromoCode.code == bad_code)) is None
