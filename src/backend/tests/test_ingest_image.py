"""POST /api/ingest/image reads the photo through the ml sidecar's /v1/ocr (E0-QA.9).

Under ENVIRONMENT=test get_ml_client() is the FakeMLClient, whose OCR returns
the upload's UTF-8 lines, so a "photo" here is text bytes with an image type.
"""

import uuid

import pytest

from app.clients.errors import ModelServiceError, ModelServiceUnavailable
from app.services import vision_service


async def _headers(client, promo_code: str) -> dict:
    r = await client.post("/api/auth/register", json={
        "email": f"ocr_{uuid.uuid4().hex[:8]}@example.com", "password": "password123",
        "display_name": "OCR", "promo_code": promo_code,
    })
    assert r.status_code in (200, 201), r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _post(client, headers, data: bytes):
    return await client.post("/api/ingest/image", files={"file": ("notes.png", data, "image/png")},
                             headers=headers)


class _Raising:
    def __init__(self, exc):
        self.exc, self.calls = exc, []

    async def ocr(self, image, filename="image"):
        self.calls.append((image, filename))
        raise self.exc


@pytest.mark.asyncio
async def test_extracted_text_comes_from_the_ml_client(client, promo_code):
    r = await _post(client, await _headers(client, promo_code), b"  Met Meepo  \n\n Borin found a +1 dagger \n")
    assert r.status_code == 200, r.text
    assert r.json() == {"extracted_text": "Met Meepo\nBorin found a +1 dagger"}


@pytest.mark.asyncio
async def test_no_text_is_422(client, promo_code):
    r = await _post(client, await _headers(client, promo_code), b"\x89PNG\r\n\x1a\n\xff\xfe")
    assert r.status_code == 422, r.text
    assert "Could not extract text" in r.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.parametrize("exc,status,needle", [
    (ModelServiceUnavailable("ml down"), 503, "unavailable"),
    (ModelServiceError("ml /v1/ocr: not an image", status_code=422), 422, "Could not extract text"),
    (ModelServiceError("ml /v1/ocr: too large", status_code=413), 413, "10 MB"),
])
async def test_sidecar_errors_map_to_http(client, promo_code, monkeypatch, exc, status, needle):
    fake = _Raising(exc)
    monkeypatch.setattr(vision_service, "get_ml_client", lambda: fake)
    r = await _post(client, await _headers(client, promo_code), b"text")
    assert r.status_code == status, r.text
    assert needle in r.json()["detail"]
    assert fake.calls == [(b"text", "notes.png")]


def test_vision_service_loads_no_model_package():
    src = (vision_service.__file__ and open(vision_service.__file__).read()) or ""
    for pkg in ("easyocr", "rapidocr", "onnxruntime", "torch", "PIL"):
        assert f"import {pkg}" not in src
