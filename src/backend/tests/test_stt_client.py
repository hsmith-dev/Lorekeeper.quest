"""app/clients/stt.py against httpx.MockTransport (the I/O matrix client rows),
the deterministic fake, client selection, the stt settings, and the removal
of the in-process openai-whisper path (E0-Platform.5). No database needed."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.clients.errors import ModelServiceError, ModelServiceUnavailable, is_retryable
from app.clients.fakes import FakeSTTClient
from app.clients.stt import STTClient, Transcript, TranscriptSegment, get_stt_client
from app.core.config import Settings

BACKEND = Path(__file__).resolve().parents[1]

GOOD = {"text": "Borin enters the tavern.", "language": "en",
        "segments": [{"start_ms": 0, "end_ms": 1200, "text": "Borin enters"},
                     {"start_ms": 1200, "end_ms": 2000, "text": "the tavern."}],
        "rtf": 0.25}


def _client(handler) -> STTClient:
    return STTClient("http://stt:8000", 5.0, transport=httpx.MockTransport(handler))


def _settings(**kw) -> Settings:
    base = dict(database_url="postgresql+asyncpg://u:p@h/db_test", postgres_password="p", secret_key="k")
    return Settings(**{**base, **kw})


def _multipart(req: httpx.Request) -> dict[str, tuple[str | None, bytes]]:
    """name -> (filename, body) for each part of a multipart request."""
    ctype = req.headers["content-type"]
    assert ctype.startswith("multipart/form-data; boundary=")
    boundary = ctype.split("boundary=", 1)[1].encode()
    parts = {}
    for chunk in req.content.split(b"--" + boundary)[1:-1]:
        head, _, body = chunk.strip(b"\r\n").partition(b"\r\n\r\n")
        disp = next(line for line in head.split(b"\r\n") if line.lower().startswith(b"content-disposition"))
        attrs = dict(
            (k.strip(), v.strip().strip(b'"'))
            for k, _, v in (a.partition(b"=") for a in disp.split(b";")[1:])
        )
        filename = attrs.get(b"filename")
        parts[attrs[b"name"].decode()] = (filename.decode() if filename is not None else None, body)
    return parts


# ── happy paths ─────────────────────────────────────────────────────────────

async def test_transcribe_container_posts_one_file_part():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(200, json=GOOD)

    t = await _client(handler).transcribe(b"OggS audio bytes")
    req = seen["req"]
    assert req.method == "POST"
    assert str(req.url) == "http://stt:8000/v1/transcribe"  # no format query
    parts = _multipart(req)
    assert set(parts) == {"file"}  # no initial_prompt field when none is given
    assert parts["file"] == ("audio", b"OggS audio bytes")
    assert t == Transcript(
        text="Borin enters the tavern.", language="en",
        segments=[TranscriptSegment(0, 1200, "Borin enters"), TranscriptSegment(1200, 2000, "the tavern.")],
        rtf=0.25,
    )


async def test_transcribe_pcm16_sends_format_query_and_prompt_field():
    seen = {}

    def handler(req: httpx.Request):
        seen["req"] = req
        return httpx.Response(200, json=GOOD)

    pcm = b"\x00\x40" * 8
    prompt = "Borin Stonebeard, Waterdeep, " * 40  # long: must stay out of the URL
    await _client(handler).transcribe(pcm, initial_prompt=prompt, format="pcm16")
    req = seen["req"]
    assert req.url.path == "/v1/transcribe"
    assert dict(req.url.params) == {"format": "pcm16"}
    assert "Borin" not in str(req.url)
    parts = _multipart(req)
    assert set(parts) == {"file", "initial_prompt"}
    assert parts["file"] == ("audio", pcm)
    assert parts["initial_prompt"] == (None, prompt.encode())


async def test_transcribe_null_language_and_int_rtf():
    body = {**GOOD, "language": None, "segments": [], "rtf": 0}
    t = await _client(lambda req: httpx.Response(200, json=body)).transcribe(b"x")
    assert t.language is None and t.segments == [] and t.rtf == 0.0


async def test_status_parses():
    def handler(req):
        assert req.method == "GET" and req.url.path == "/v1/status"
        return httpx.Response(200, json={
            "models": [{"name": "faster-whisper-base", "kind": "stt", "state": "not_loaded"}],
            "compute_type": "int8", "device": "cpu", "rss_bytes": 123})

    st = await _client(handler).status()
    assert st.compute_type == "int8" and st.device == "cpu" and st.rss_bytes == 123
    assert [(m.name, m.kind, m.state) for m in st.models] == [("faster-whisper-base", "stt", "not_loaded")]


# ── sidecar down / timeout / 5xx -> ModelServiceUnavailable ────────────────

@pytest.mark.parametrize("exc", [
    httpx.ConnectError("refused"),
    httpx.ReadTimeout("slow"),
    httpx.ConnectTimeout("slow"),
    httpx.RemoteProtocolError("hung up"),
])
async def test_transport_failures_are_unavailable(exc):
    def handler(req):
        raise exc

    with pytest.raises(ModelServiceUnavailable) as info:
        await _client(handler).transcribe(b"x")
    assert is_retryable(info.value)


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_is_unavailable(status):
    with pytest.raises(ModelServiceUnavailable) as info:
        await _client(lambda req: httpx.Response(status, json={"detail": "speech model unavailable"})).transcribe(b"x")
    assert info.value.status_code == status


# ── contract break -> ModelServiceError (not retryable) ───────────────────

def _assert_terminal(info):
    assert type(info.value) is ModelServiceError
    assert not is_retryable(info.value)


@pytest.mark.parametrize("status", [400, 404, 413, 422])
async def test_4xx_is_contract_error_with_status(status):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(status, json={"detail": "bad"})).transcribe(b"x")
    _assert_terminal(info)
    assert info.value.status_code == status


@pytest.mark.parametrize("body", [
    {**GOOD, "text": None},
    {**GOOD, "text": 3},
    {**GOOD, "language": 1},
    {**GOOD, "segments": None},
    {**GOOD, "segments": [{"start_ms": 0, "end_ms": 1}]},
    {**GOOD, "segments": [{"start_ms": "0", "end_ms": 1, "text": "a"}]},
    {**GOOD, "segments": [{"start_ms": 0.5, "end_ms": 1, "text": "a"}]},
    {**GOOD, "segments": ["a"]},
    {**GOOD, "rtf": "fast"},
    {**GOOD, "rtf": True},
    {k: v for k, v in GOOD.items() if k != "rtf"},
    ["not", "an", "object"],
])
async def test_transcribe_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).transcribe(b"x")
    _assert_terminal(info)


async def test_non_json_is_contract_error():
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, text="<html>")).transcribe(b"x")
    _assert_terminal(info)


async def test_other_httpx_errors_stay_typed():
    def handler(req):
        raise httpx.DecodingError("bad gzip")

    with pytest.raises(ModelServiceError) as info:
        await _client(handler).transcribe(b"x")
    _assert_terminal(info)


@pytest.mark.parametrize("body", [
    {}, [], {"models": [{}], "compute_type": "int8", "device": "cpu", "rss_bytes": 1},
    {"models": [], "compute_type": "int8", "device": "cpu", "rss_bytes": "x"},
    {"models": [], "compute_type": "int8", "rss_bytes": 1},
    {"models": [{"name": 1, "kind": "stt", "state": "loaded"}], "compute_type": "int8",
     "device": "cpu", "rss_bytes": 1},
])
async def test_status_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).status()
    _assert_terminal(info)


# ── fake ──────────────────────────────────────────────────────────────────

async def test_fake_rejects_empty_and_odd_pcm16_with_422():
    fake = FakeSTTClient()
    for audio, fmt in ((b"", None), (b"", "pcm16"), (b"\x01\x02\x03", "pcm16")):
        with pytest.raises(ModelServiceError) as info:
            await fake.transcribe(audio, format=fmt)
        assert type(info.value) is ModelServiceError
        assert info.value.status_code == 422
    # Odd length is only a PCM16 rule; a container may have any length.
    assert (await fake.transcribe(b"\x01\x02\x03")).text


async def test_fake_silence_is_empty_text():
    fake = FakeSTTClient()
    assert (await fake.transcribe(b"\0" * 3200, format="pcm16")).text == ""
    assert (await fake.transcribe(b"\0" * 7)).text == ""


async def test_fake_is_deterministic_and_non_empty():
    fake = FakeSTTClient()
    a1 = await fake.transcribe(b"audio a", initial_prompt="Borin")
    a2 = await fake.transcribe(b"audio a")
    b = await fake.transcribe(b"audio b")
    assert a1 == a2 and a1.text != b.text
    assert a1.text.strip() and a1.language == "en"
    pcm = await fake.transcribe(b"\x01\x00" * 16000, format="pcm16")
    assert pcm.segments == [TranscriptSegment(0, 1000, pcm.text)]


async def test_fake_status_is_not_loaded():
    st = await FakeSTTClient().status()
    assert [(m.name, m.kind, m.state) for m in st.models] == [("faster-whisper-base", "stt", "not_loaded")]


# ── selection + settings ──────────────────────────────────────────────────

def test_get_stt_client_selects_fake_under_test_env():
    assert isinstance(get_stt_client(_settings(environment="test")), FakeSTTClient)
    assert isinstance(get_stt_client(_settings(environment="development")), STTClient)


def test_client_from_settings_is_cached():
    s = _settings(environment="production", stt_url="http://stt:9000/", stt_timeout_s=42.0)
    client = get_stt_client(s)
    assert isinstance(client, STTClient)
    assert client.base_url == "http://stt:9000"
    assert client.timeout_s == 42.0
    assert get_stt_client(s) is client


def test_settings_defaults():
    s = _settings()
    assert s.stt_url == "http://stt:8000"
    assert s.stt_timeout_s == 300.0
    assert s.stt_compute_type == "int8"


@pytest.mark.parametrize("raw,expected", [
    ("int8", "int8"), ("float32", "float32"), ("float16", "float16"), ("int8_float16", "int8_float16"),
    (" FLOAT32 ", "float32"), ("Int8", "int8"), ("", "int8"), ("   ", "int8"),
])
def test_stt_compute_type_accepts_the_sidecar_set(raw, expected):
    assert _settings(stt_compute_type=raw).stt_compute_type == expected


@pytest.mark.parametrize("bad", ["bogus", "int4", "fp16"])
def test_stt_compute_type_rejects_unknown(bad):
    with pytest.raises(ValidationError):
        _settings(stt_compute_type=bad)


def test_stt_compute_types_match_the_sidecar():
    sidecar_config = BACKEND.parent / "services" / "stt" / "stt_service" / "config.py"
    if not sidecar_config.exists():
        pytest.skip("src/services/stt not in this checkout")
    (node,) = [n for n in ast.parse(sidecar_config.read_text()).body
               if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "COMPUTE_TYPES" for t in n.targets)]
    sidecar = set(ast.literal_eval(node.value))
    backend = set(Settings.model_fields["stt_compute_type"].annotation.__args__)
    assert backend == sidecar


# ── openai-whisper is gone ────────────────────────────────────────────────

def test_openai_whisper_removed_from_requirements():
    reqs = (BACKEND / "requirements.txt").read_text().lower()
    assert "openai-whisper" not in reqs
    assert "whisper" not in reqs


def test_transcription_service_is_a_thin_client_wrapper():
    path = BACKEND / "app" / "services" / "transcription_service.py"
    src = path.read_text()
    assert "ThreadPoolExecutor" not in src
    assert "run_in_executor" not in src
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "whisper" not in imported and "concurrent" not in imported


async def test_transcription_service_strips_client_text(monkeypatch):
    from app.services import transcription_service

    seen = {}

    class Stub:
        async def transcribe(self, audio, *, initial_prompt=None, format=None):
            seen.update(audio=audio, initial_prompt=initial_prompt, format=format)
            return Transcript(text="  hello there \n", language="en")

    monkeypatch.setattr("app.clients.stt.get_stt_client", lambda: Stub())
    out = await transcription_service.transcribe(b"pcm", initial_prompt="Borin", format="pcm16")
    assert out == "hello there"
    assert seen == {"audio": b"pcm", "initial_prompt": "Borin", "format": "pcm16"}


async def test_module_level_transcribe_delegates_to_the_client(monkeypatch):
    from app.clients import stt

    seen = {}
    expected = Transcript(text="Borin enters.", language="en",
                          segments=[TranscriptSegment(0, 900, "Borin enters.")], rtf=0.1)

    class Stub:
        async def transcribe(self, audio, *, initial_prompt=None, format=None):
            seen.update(audio=audio, initial_prompt=initial_prompt, format=format)
            return expected

    monkeypatch.setattr(stt, "get_stt_client", lambda: Stub())
    assert await stt.transcribe(b"webm", initial_prompt="Borin") is expected
    assert seen == {"audio": b"webm", "initial_prompt": "Borin", "format": None}
    assert await stt.transcribe(b"\x00\x01", format="pcm16") is expected
    assert seen["format"] == "pcm16" and seen["initial_prompt"] is None


async def test_module_level_transcribe_uses_the_fake_under_test_env(monkeypatch):
    from app.clients import stt

    monkeypatch.setattr(stt, "get_settings", lambda: _settings(environment="test"))
    t = await stt.transcribe(b"some audio")
    assert t.text.startswith("Fake transcript ")
    with pytest.raises(ModelServiceError) as info:
        await stt.transcribe(b"")
    assert info.value.status_code == 422
