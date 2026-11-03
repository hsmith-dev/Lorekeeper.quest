"""POST /api/ingest/voice through the real app, on the stt client (the fake
under ENVIRONMENT=test), plus the sidecar-error mapping (E0-Platform.5)."""

from __future__ import annotations

import uuid

import pytest

from app.clients.errors import ModelServiceError, ModelServiceUnavailable

URL = "/api/ingest/voice"
UNTRANSCRIBABLE = "Could not transcribe audio. Try speaking more clearly."


async def _auth(client, promo_code: str) -> dict:
    r = await client.post("/api/auth/register", json={
        "email": f"voice_{uuid.uuid4().hex[:8]}@example.com", "password": "password123",
        "display_name": "Voice", "promo_code": promo_code,
    })
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _upload(client, headers, data: bytes, content_type: str = "audio/webm"):
    return await client.post(URL, files={"file": ("recording.webm", data, content_type)}, headers=headers)


async def test_voice_returns_the_fake_transcript(client, promo_code):
    headers = await _auth(client, promo_code)
    r = await _upload(client, headers, b"\x1aE\xdf\xa3 webm bytes")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"transcribed_text"}
    assert body["transcribed_text"].startswith("Fake transcript ")


@pytest.mark.parametrize("content_type", ["audio/ogg", "audio/wav", "audio/mpeg", "audio/mp4", "audio/x-m4a"])
async def test_voice_accepts_every_audio_type(client, promo_code, content_type):
    headers = await _auth(client, promo_code)
    assert (await _upload(client, headers, b"some audio", content_type)).status_code == 200


async def test_voice_silence_is_422(client, promo_code):
    headers = await _auth(client, promo_code)
    r = await _upload(client, headers, b"\0" * 4096)
    assert r.status_code == 422
    assert r.json()["detail"] == UNTRANSCRIBABLE


async def test_voice_empty_upload_is_422_before_the_sidecar(client, promo_code, monkeypatch):
    def never():
        raise AssertionError("the sidecar must not be called for an empty upload")

    monkeypatch.setattr("app.clients.stt.get_stt_client", never)
    headers = await _auth(client, promo_code)
    r = await _upload(client, headers, b"")
    assert r.status_code == 422
    assert r.json()["detail"] == UNTRANSCRIBABLE


async def test_voice_wrong_type_is_415(client, promo_code):
    headers = await _auth(client, promo_code)
    r = await _upload(client, headers, b"hello", "text/plain")
    assert r.status_code == 415


async def test_voice_over_25_mb_is_413(client, promo_code):
    headers = await _auth(client, promo_code)
    r = await _upload(client, headers, b"\x01" * (25 * 1024 * 1024 + 1))
    assert r.status_code == 413


async def test_voice_requires_auth(client):
    assert (await _upload(client, {}, b"audio")).status_code in (401, 403)


class _Raising:
    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    async def transcribe(self, audio, *, initial_prompt=None, format=None):
        self.calls += 1
        raise self.exc


@pytest.mark.parametrize("exc,status,detail", [
    (ModelServiceUnavailable("stt sidecar unreachable"), 503, "Speech model unavailable"),
    (ModelServiceUnavailable("stt sidecar returned 503", status_code=503), 503, "Speech model unavailable"),
    (ModelServiceError("stt sidecar rejected /v1/transcribe with 422", status_code=422), 422, UNTRANSCRIBABLE),
    (ModelServiceError("stt sidecar rejected /v1/transcribe with 413", status_code=413), 422, UNTRANSCRIBABLE),
    (ModelServiceError("stt /v1/transcribe: malformed response"), 503, "Speech model unavailable"),
])
async def test_voice_maps_sidecar_errors(client, promo_code, monkeypatch, exc, status, detail):
    stub = _Raising(exc)
    monkeypatch.setattr("app.clients.stt.get_stt_client", lambda: stub)
    headers = await _auth(client, promo_code)
    r = await _upload(client, headers, b"real-looking audio")
    assert r.status_code == status
    assert r.json() == {"detail": detail}
    assert stub.calls == 1
