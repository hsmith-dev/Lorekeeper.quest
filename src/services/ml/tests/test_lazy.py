"""Lazy NLI and OCR under the resident-memory budget (the E0-Platform.4 matrix).

Fake NLI and OCR models; no torch, transformers or rapidocr needed. The
RapidOcrReader post-processing test needs PIL and skips without it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ml_service.app import create_app
from ml_service.budget import BudgetExceeded, LazySlot, ResidentBudget, release_memory
from ml_service.config import (
    MAX_NLI_CHARS,
    MAX_NLI_PAIRS,
    MAX_OCR_BYTES,
    NLI_MODEL_SHA256,
    OCR_MODELS,
    Config,
)
from ml_service.models import NLI_LABELS, InvalidImage, ModelSlot, RapidOcrReader

from .conftest import FakeEmbedder, FakeNer

REPO = Path(__file__).resolve().parents[4]
PNG = b"\x89PNG\r\n\x1a\n" + b"fake image body"
BUDGET_BODY = {"detail": "ml budget exceeded", "code": "ml_budget"}
# The story's eviction case: both lazy models cannot be resident together.
TIGHT = Config(resident_budget_mb=2000, nli_cost_mb=1200, ocr_cost_mb=1000)


class FakeNli:
    def __init__(self, gate: threading.Event | None = None, started: threading.Event | None = None):
        self.chunks: list[int] = []
        self._gate, self._started = gate, started

    @staticmethod
    def expected(premise: str, hypothesis: str) -> dict[str, float]:
        seed = hashlib.sha256(f"{premise}|{hypothesis}".encode()).digest()
        logits = [seed[i] / 64.0 for i in range(3)]
        exps = [math.exp(x) for x in logits]
        return {k: e / sum(exps) for k, e in zip(NLI_LABELS, exps)}

    def score(self, pairs):
        self.chunks.append(len(pairs))
        if self._started:
            self._started.set()
        if self._gate:
            assert self._gate.wait(10), "test gate never opened"
        return [self.expected(p, h) for p, h in pairs]


class FakeOcr:
    def __init__(self):
        self.calls = 0

    def read(self, image_bytes: bytes) -> str:
        self.calls += 1
        if not image_bytes.startswith(b"\x89PNG"):
            raise InvalidImage("not a decodable image: UnidentifiedImageError")
        return "Mira died in the fire\nat the Silver Stag"


class Factory:
    """Counts loads; raises `fail` times before handing out the model."""

    def __init__(self, model, fail: int = 0):
        self.model, self.fail, self.loads = model, fail, 0

    def __call__(self, cfg):
        self.loads += 1
        if self.fail:
            self.fail -= 1
            raise RuntimeError("weights missing")
        return self.model


def _app(cfg: Config = Config(), nli=None, ocr=None):
    nli = nli if nli is not None else Factory(FakeNli())
    ocr = ocr if ocr is not None else Factory(FakeOcr())
    return create_app(cfg, embedder_factory=lambda c: FakeEmbedder(), ner_factory=lambda c: FakeNer(),
                      nli_factory=nli, ocr_factory=ocr)


def _states(client) -> dict[str, str]:
    return {m["kind"]: m["state"] for m in client.get("/v1/status").json()["models"]}


def _pairs(n: int) -> list[dict[str, str]]:
    return [{"premise": f"premise {i}", "hypothesis": f"hypothesis {i}"} for i in range(n)]


def _ocr(client, data: bytes = PNG):
    return client.post("/v1/ocr", files={"file": ("page.png", data, "image/png")})


# ── boot ─────────────────────────────────────────────────────────────────

def test_boot_loads_only_resident_models():
    nli, ocr = Factory(FakeNli()), Factory(FakeOcr())
    with TestClient(_app(nli=nli, ocr=ocr)) as c:
        assert c.get("/healthz").status_code == 200
        assert _states(c) == {"embedding": "loaded", "ner": "loaded", "nli": "not_loaded", "ocr": "not_loaded"}
        status = c.get("/v1/status").json()
        assert status["lazy_resident_mb"] == 0 and status["resident_budget_mb"] == 2000
    assert nli.loads == 0 and ocr.loads == 0


def test_healthz_ignores_failed_lazy_models():
    with TestClient(_app(nli=Factory(FakeNli(), fail=1))) as c:
        assert c.post("/v1/nli", json={"pairs": _pairs(1)}).status_code == 500
        assert _states(c)["nli"] == "failed"
        assert c.get("/healthz").status_code == 200


# ── nli ──────────────────────────────────────────────────────────────────

def test_nli_chunks_and_order():
    fake = FakeNli()
    with TestClient(_app(nli=Factory(fake))) as c:
        pairs = _pairs(50)
        r = c.post("/v1/nli", json={"pairs": pairs})
        assert r.status_code == 200
        scores = r.json()["scores"]
        assert fake.chunks == [32, 18]
        assert len(scores) == 50
        for pair, s in zip(pairs, scores):
            assert set(s) == {"entailment", "neutral", "contradiction"}
            assert math.isclose(sum(s.values()), 1.0, rel_tol=1e-9)
            want = FakeNli.expected(pair["premise"], pair["hypothesis"])
            assert all(math.isclose(s[k], want[k]) for k in NLI_LABELS)  # input order kept
        assert _states(c)["nli"] == "loaded"
        assert c.get("/v1/status").json()["lazy_resident_mb"] == 600


def test_nli_batch_size_from_config():
    fake = FakeNli()
    with TestClient(_app(Config(nli_batch_size=8), nli=Factory(fake))) as c:
        assert c.post("/v1/nli", json={"pairs": _pairs(20)}).status_code == 200
    assert fake.chunks == [8, 8, 4]


def test_nli_empty_does_not_load():
    nli = Factory(FakeNli())
    with TestClient(_app(nli=nli)) as c:
        r = c.post("/v1/nli", json={"pairs": []})
        assert r.status_code == 200 and r.json() == {"scores": []}
        assert _states(c)["nli"] == "not_loaded"
    assert nli.loads == 0


def test_nli_limits_and_bad_bodies():
    nli = Factory(FakeNli())
    with TestClient(_app(nli=nli)) as c:
        assert c.post("/v1/nli", json={"pairs": _pairs(MAX_NLI_PAIRS + 1)}).status_code == 422
        long = "a" * (MAX_NLI_CHARS + 1)
        assert c.post("/v1/nli", json={"pairs": [{"premise": long, "hypothesis": "b"}]}).status_code == 422
        assert c.post("/v1/nli", json={"pairs": [{"premise": "a", "hypothesis": long}]}).status_code == 422
        assert c.post("/v1/nli", json={"pairs": [{"premise": "a"}]}).status_code == 422
        assert c.post("/v1/nli", json={}).status_code == 422
        assert nli.loads == 0  # rejected before the model is touched
        edge = "a" * MAX_NLI_CHARS
        assert c.post("/v1/nli", json={"pairs": [{"premise": edge, "hypothesis": edge}]}).status_code == 200
        assert c.post("/v1/nli", json={"pairs": _pairs(MAX_NLI_PAIRS)}).status_code == 200


# ── ocr ──────────────────────────────────────────────────────────────────

def test_ocr_returns_text_and_loads_lazily():
    ocr = Factory(FakeOcr())
    with TestClient(_app(ocr=ocr)) as c:
        r = _ocr(c)
        assert r.status_code == 200
        assert r.json() == {"text": "Mira died in the fire\nat the Silver Stag"}
        assert _states(c)["ocr"] == "loaded"
        assert _ocr(c).status_code == 200
    assert ocr.loads == 1


def test_ocr_bad_images():
    ocr = Factory(FakeOcr())
    with TestClient(_app(ocr=ocr)) as c:
        r = _ocr(c, b"")
        assert r.status_code == 422 and r.json()["code"] == "invalid_image"
        assert ocr.loads == 0  # an empty upload never loads the model
        r = _ocr(c, b"this is not an image")
        assert r.status_code == 422 and r.json()["code"] == "invalid_image"
        assert c.post("/v1/ocr", files={"other": ("x.png", PNG, "image/png")}).status_code == 422
        assert c.post("/v1/ocr").status_code == 422


def test_ocr_too_big():
    ocr = Factory(FakeOcr())
    with TestClient(_app(ocr=ocr)) as c:
        assert _ocr(c, PNG + b"\0" * (MAX_OCR_BYTES - len(PNG))).status_code == 200
        assert _ocr(c, PNG + b"\0" * (MAX_OCR_BYTES - len(PNG) + 1)).status_code == 413


# ── budget and eviction ──────────────────────────────────────────────────

def test_evicts_idle_lru_model_to_make_room():
    nli, ocr = Factory(FakeNli()), Factory(FakeOcr())
    app = _app(TIGHT, nli=nli, ocr=ocr)
    with TestClient(app) as c:
        assert c.post("/v1/nli", json={"pairs": _pairs(1)}).status_code == 200
        assert _ocr(c).status_code == 200
        assert _states(c) == {"embedding": "loaded", "ner": "loaded", "nli": "not_loaded", "ocr": "loaded"}
        assert c.get("/v1/status").json()["lazy_resident_mb"] == 1000
        # And back: NLI reloads, evicting OCR.
        assert c.post("/v1/nli", json={"pairs": _pairs(1)}).status_code == 200
        assert _states(c)["ocr"] == "not_loaded" and _states(c)["nli"] == "loaded"
    assert nli.loads == 2 and ocr.loads == 1
    assert app.state.budget.evictions == 2


def test_default_costs_fit_both_models():
    app = _app()
    with TestClient(app) as c:
        assert c.post("/v1/nli", json={"pairs": _pairs(1)}).status_code == 200
        assert _ocr(c).status_code == 200
        assert _states(c)["nli"] == "loaded" and _states(c)["ocr"] == "loaded"
        assert c.get("/v1/status").json()["lazy_resident_mb"] == 1000
    assert app.state.budget.evictions == 0


def test_busy_model_is_never_evicted():
    gate, started = threading.Event(), threading.Event()
    fake_nli, ocr = FakeNli(gate=gate, started=started), Factory(FakeOcr())
    app = _app(TIGHT, nli=Factory(fake_nli), ocr=ocr)
    with TestClient(app) as c, ThreadPoolExecutor(1) as pool:
        busy = pool.submit(c.post, "/v1/nli", json={"pairs": _pairs(3)})
        assert started.wait(10)  # NLI is loaded and serving
        r = _ocr(c)
        assert r.status_code == 503
        assert r.json() == BUDGET_BODY
        assert _states(c)["nli"] == "loaded" and _states(c)["ocr"] == "not_loaded"
        assert ocr.loads == 0
        gate.set()
        assert busy.result(10).status_code == 200
        # Idle now, so the same OCR request evicts it.
        assert _ocr(c).status_code == 200
        assert _states(c)["nli"] == "not_loaded"


def test_cost_over_budget_is_503_and_evicts_nothing():
    nli, ocr = Factory(FakeNli()), Factory(FakeOcr())
    app = _app(Config(resident_budget_mb=1000, nli_cost_mb=600, ocr_cost_mb=1001), nli=nli, ocr=ocr)
    with TestClient(app) as c:
        assert c.post("/v1/nli", json={"pairs": _pairs(1)}).status_code == 200
        r = _ocr(c)
        assert r.status_code == 503 and r.json() == BUDGET_BODY
        assert _states(c)["nli"] == "loaded" and _states(c)["ocr"] == "not_loaded"
        assert c.get("/v1/status").json()["lazy_resident_mb"] == 600
    assert ocr.loads == 0 and app.state.budget.evictions == 0


def test_load_failure_is_500_and_releases_the_reservation():
    nli = Factory(FakeNli(), fail=1)
    with TestClient(_app(TIGHT, nli=nli)) as c:
        r = c.post("/v1/nli", json={"pairs": _pairs(1)})
        assert r.status_code == 500 and r.json()["code"] == "ml_load_failed"
        assert _states(c)["nli"] == "failed"
        assert c.get("/v1/status").json()["lazy_resident_mb"] == 0
        # The released reservation leaves room for OCR without evicting anything.
        assert _ocr(c).status_code == 200
        assert _states(c)["ocr"] == "loaded"
        # A later request retries the load (evicting the idle OCR to fit).
        assert c.post("/v1/nli", json={"pairs": _pairs(1)}).status_code == 200
        assert _states(c)["nli"] == "loaded"
    assert nli.loads == 2


def _slots(budget_mb: int, *costs: int):
    budget = ResidentBudget(budget_mb, on_evict=lambda: None)
    slots = [LazySlot(f"m{i}", "x", object, cost, budget) for i, cost in enumerate(costs)]
    return budget, slots


def test_budget_evicts_least_recently_used_first_and_only_as_needed():
    budget, (a, b, c) = _slots(100, 40, 40, 40)
    a.run(lambda m: None)
    b.run(lambda m: None)
    a.run(lambda m: None)  # b is now the least recently used
    c.run(lambda m: None)
    assert (a.state, b.state, c.state) == ("loaded", "not_loaded", "loaded")
    assert budget.resident_mb == 80 and budget.evictions == 1


def test_budget_skips_in_use_slots_and_never_partially_evicts():
    budget, (a, b, c) = _slots(100, 50, 30, 60)
    a.run(lambda m: None)
    b.run(lambda m: None)
    budget.acquire(a)  # a is serving; only b (30) is idle, not enough for c (60)
    with pytest.raises(BudgetExceeded):
        c.run(lambda m: None)
    assert (a.state, b.state, c.state) == ("loaded", "loaded", "not_loaded")
    assert budget.evictions == 0 and c.in_use == 0 and not c.reserved
    budget.release(a)
    c.run(lambda m: None)  # both idle now; c needs 40 more MB, so b (30) alone is not enough
    assert (a.state, b.state, c.state) == ("not_loaded", "not_loaded", "loaded")
    assert budget.resident_mb == 60 and budget.evictions == 2


def test_concurrent_requests_share_one_load():
    budget = ResidentBudget(100, on_evict=lambda: None)
    loads = []
    slot = LazySlot("n", "x", lambda: loads.append(1) or object(), 40, budget)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: slot.run(lambda m: m), range(32)))
    assert len(loads) == 1 and slot.in_use == 0 and budget.resident_mb == 40


def test_unload_drops_the_reference():
    slot = ModelSlot("m", "x", object)
    assert slot.state == "not_loaded"
    slot.load()
    assert slot.state == "loaded" and slot.is_loaded
    slot.unload()
    assert slot.state == "not_loaded" and not slot.is_loaded


def test_release_memory_is_safe_everywhere():
    release_memory()  # glibc: malloc_trim(0); elsewhere only gc.collect()


# ── RapidOcrReader post-processing (the old vision_service rule) ─────────

class StubEngine:
    """Stands in for rapidocr.RapidOCR: called with a PIL image, returns an
    object with .txts (None when nothing was found)."""

    def __init__(self, lines):
        self.lines, self.calls = lines, []

    def __call__(self, image):
        self.calls.append((image.mode, image.size))

        class Out:
            txts = self.lines

        return Out()


needs_pil = pytest.mark.skipif(importlib.util.find_spec("PIL") is None, reason="PIL not installed")


def _png(mode: str = "RGBA", size=(12, 7), exif_orientation: int | None = None) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    image = Image.new(mode, size)
    if exif_orientation is None:
        image.save(buf, format="PNG")
    else:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        image.convert("RGB").save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


@needs_pil
@pytest.mark.parametrize("mode", ["RGBA", "L", "P", "RGB"])
def test_rapidocr_reader_keeps_the_vision_service_rule(mode):
    stub = StubEngine(("  Mira died in the fire  ", "", "   ", "at the Silver Stag\t"))
    reader = RapidOcrReader("/unused", engine=stub)
    assert reader.read(_png(mode)) == "Mira died in the fire\nat the Silver Stag"
    assert stub.calls == [("RGB", (12, 7))]  # convert("RGB") before OCR


@needs_pil
def test_rapidocr_reader_applies_exif_orientation():
    stub = StubEngine(("x",))
    RapidOcrReader("/unused", engine=stub).read(_png("RGB", size=(12, 7), exif_orientation=6))
    assert stub.calls == [("RGB", (7, 12))]  # a phone photo taken sideways, turned upright


@needs_pil
def test_rapidocr_reader_no_text_is_empty_string():
    assert RapidOcrReader("/unused", engine=StubEngine(None)).read(_png()) == ""


@needs_pil
def test_rapidocr_reader_rejects_non_images():
    stub = StubEngine(("x",))
    reader = RapidOcrReader("/unused", engine=stub)
    for data in (b"", b"not an image", _png()[:40]):
        with pytest.raises(InvalidImage):
            reader.read(data)
    assert stub.calls == []


def test_rapidocr_reader_needs_the_baked_files(tmp_path):
    if importlib.util.find_spec("rapidocr") is None:
        pytest.skip("rapidocr not installed")
    with pytest.raises(FileNotFoundError):
        RapidOcrReader(str(tmp_path))


REGISTER = REPO / "licenses" / "register.yaml"


@pytest.mark.skipif(not REGISTER.exists(), reason="licence register not in this checkout")
@pytest.mark.parametrize("name,url,sha", [
    ("nli-deberta-v3-xsmall", None, NLI_MODEL_SHA256),
    *[(name, url, sha) for name, _file, url, sha in OCR_MODELS],
])
def test_baked_weights_match_the_register(name, url, sha):
    m = re.search(rf"^  - name: {re.escape(name)}\n(?P<body>(?:    .*\n)+)", REGISTER.read_text(), re.M)
    assert m, f"{name} missing from licenses/register.yaml"
    body = m.group("body")
    assert f"sha256: {sha}" in body
    assert re.search(r"images: \[[^\]]*\bml\b", body), f"{name} must list ml in images"
    if url:
        assert f"download: {url}" in body
