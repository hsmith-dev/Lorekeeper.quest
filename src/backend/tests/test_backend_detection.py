"""E0-LLM.3: llm_provider.detect_backend and generate_narrative's use of it.

Backends are an httpx.MockTransport on llm_provider._transport and the gate
is fakeredis-backed, so no test opens a socket to KOBOLD_URL.
"""

import uuid

import fakeredis
import httpx
import pytest
import pytest_asyncio

from app.core import llm_gate
from app.core.config import get_settings
from app.core.llm_gate import GateClass, LLMGate
from app.services import llm_provider
from app.services.llm_provider import BACKEND_OLLAMA, BACKEND_OPENAI_COMPAT, LLMConfig, detect_backend


class Server:
    """Answers GET /api/version with `version` (a callable returning an
    httpx.Response, or raising), 404s the KoboldCpp-native endpoint, and
    serves OpenAI-compatible chat completions."""

    def __init__(self, version):
        self.version = version
        self.version_calls = 0
        self.native_calls = 0
        self.chat_calls = 0
        self.paths: list[str] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(f"{request.method} {request.url.path}")
        if request.url.path == "/api/version":
            self.version_calls += 1
            return self.version(request)
        if request.url.path == "/api/v1/generate":
            self.native_calls += 1
            return httpx.Response(404, text="404 page not found")
        if request.url.path == "/v1/chat/completions":
            self.chat_calls += 1
            return httpx.Response(200, json={"choices": [{"message": {"content": "A tale."}}]})
        return httpx.Response(404)


def ollama_version(request):
    return httpx.Response(200, json={"version": "0.4.3"})


def not_found(request):
    return httpx.Response(404, text="404 page not found")


def html_page(request):
    return httpx.Response(200, text="<html><body>KoboldAI Lite</body></html>",
                          headers={"content-type": "text/html"})


def refused(request):
    raise httpx.ConnectError("connection refused", request=request)


def timed_out(request):
    raise httpx.ReadTimeout("timed out", request=request)


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch):
    monkeypatch.setattr(llm_provider, "_backend_cache", {})


def serve(monkeypatch, version) -> Server:
    s = Server(version)
    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(s.handler))
    return s


class RecordingGate(LLMGate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.acquired: list[GateClass] = []

    async def acquire(self, cls, *, wait_s=None):
        self.acquired.append(GateClass(cls))
        return await super().acquire(cls, wait_s=wait_s)


@pytest_asyncio.fixture
async def gate(monkeypatch):
    redis = fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer(), decode_responses=True)
    g = RecordingGate(redis, capacity=1, wait_s=1, poll_s=0.01, key_prefix=f"test_gate:{uuid.uuid4().hex}")
    monkeypatch.setattr(llm_gate, "get_gate", lambda: g)
    yield g
    await redis.aclose()


class GateTouched(Exception):
    pass


# --- detection -----------------------------------------------------------


async def test_ollama_detected_and_cached(monkeypatch):
    s = serve(monkeypatch, ollama_version)
    assert await detect_backend("http://ollama.test:11434") == BACKEND_OLLAMA
    assert await detect_backend("http://ollama.test:11434/") == BACKEND_OLLAMA  # same cache key
    assert s.version_calls == 1
    assert llm_provider._backend_cache == {"http://ollama.test:11434": BACKEND_OLLAMA}


@pytest.mark.parametrize("version", [not_found, html_page], ids=["404", "html"])
async def test_koboldcpp_is_openai_compat_and_cached(monkeypatch, version):
    s = serve(monkeypatch, version)
    assert await detect_backend("http://kobold.test:5001") == BACKEND_OPENAI_COMPAT
    assert await detect_backend("http://kobold.test:5001") == BACKEND_OPENAI_COMPAT
    assert s.version_calls == 1


@pytest.mark.parametrize("body", [{"version": 4}, ["0.4.3"], {"name": "x"}], ids=["int", "list", "missing"])
async def test_json_without_string_version_is_openai_compat(monkeypatch, body):
    serve(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert await detect_backend("http://x.test") == BACKEND_OPENAI_COMPAT


@pytest.mark.parametrize("version", [refused, timed_out], ids=["refused", "timeout"])
async def test_down_is_openai_compat_and_not_cached(monkeypatch, version):
    s = serve(monkeypatch, version)
    assert await detect_backend("http://ollama.test:11434") == BACKEND_OPENAI_COMPAT
    assert llm_provider._backend_cache == {}
    # Ollama finished starting: the next call probes again and sees it.
    s.version = ollama_version
    assert await detect_backend("http://ollama.test:11434") == BACKEND_OLLAMA
    assert s.version_calls == 2


async def test_handler_exception_swallowed(monkeypatch):
    def broken(request):
        raise ValueError("bad handler")

    serve(monkeypatch, broken)
    assert await detect_backend("http://x.test") == BACKEND_OPENAI_COMPAT


async def test_empty_url_means_kobold_url(monkeypatch):
    s = serve(monkeypatch, ollama_version)
    hosts = []
    inner = s.handler

    async def handler(request):
        hosts.append(str(request.url))
        return await inner(request)

    monkeypatch.setattr(llm_provider, "_transport", httpx.MockTransport(handler))
    assert await detect_backend(None) == BACKEND_OLLAMA
    assert await detect_backend("") == BACKEND_OLLAMA
    assert hosts == [get_settings().kobold_url.rstrip("/") + "/api/version"]


async def test_probe_never_touches_gate(monkeypatch):
    def touched():
        raise GateTouched("detect_backend reached the gate")

    monkeypatch.setattr(llm_gate, "get_gate", touched)
    serve(monkeypatch, ollama_version)
    assert await detect_backend(None) == BACKEND_OLLAMA


# --- generate_narrative --------------------------------------------------


def platform_cfg() -> LLMConfig:
    return LLMConfig(provider="kobold", api_url=get_settings().kobold_url)


async def test_narrative_on_ollama_skips_native(monkeypatch, gate):
    from app.services import ai_service

    s = serve(monkeypatch, ollama_version)
    assert await ai_service.generate_narrative("We met a dragon.", config=platform_cfg()) == "A tale."
    assert s.native_calls == 0
    assert s.chat_calls == 1
    assert gate.acquired == [GateClass.gm_interactive]
    # The probe came first, before any LLM traffic.
    assert s.paths[0] == "GET /api/version"


async def test_narrative_on_koboldcpp_tries_native_first(monkeypatch, gate):
    from app.services import ai_service

    s = serve(monkeypatch, not_found)
    assert await ai_service.generate_narrative("We met a dragon.", config=platform_cfg()) == "A tale."
    assert s.native_calls == 3  # attempted as before, then fell back
    assert s.chat_calls == 1
    assert gate.acquired == [GateClass.gm_interactive]


async def test_narrative_probe_cached_across_calls(monkeypatch, gate):
    from app.services import ai_service

    s = serve(monkeypatch, ollama_version)
    await ai_service.generate_narrative("One.", config=platform_cfg())
    await ai_service.generate_narrative("Two.", config=platform_cfg())
    assert s.version_calls == 1
    assert s.native_calls == 0


async def test_narrative_byok_openai_never_probes(monkeypatch):
    from app.services import ai_service

    def touched():
        raise GateTouched("BYOK call reached the gate")

    monkeypatch.setattr(llm_gate, "get_gate", touched)
    s = serve(monkeypatch, ollama_version)
    out = await ai_service.generate_narrative(
        "We met a dragon.", config=LLMConfig(provider="openai", api_key="sk-test")
    )
    assert out == "A tale."
    assert s.version_calls == 0
    assert s.native_calls == 0
    assert s.paths == ["POST /v1/chat/completions"]
