"""app/clients/ml.py against httpx.MockTransport (the I/O matrix client rows),
the deterministic fake, client selection, and the single embedding contract."""

from __future__ import annotations

import ast
import math
from pathlib import Path

import httpx
import pytest

from app.clients.errors import ModelServiceError, ModelServiceUnavailable, is_retryable
from app.clients.fakes import FakeMLClient, fake_entities, fake_nli_scores, fake_vector
from app.clients.ml import (
    MAX_EMBED_TEXTS,
    MAX_NLI_PAIRS,
    MLClient,
    NamedEntity,
    NliScores,
    get_ml_client,
)
from app.core.config import Settings
from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL

BACKEND = Path(__file__).resolve().parents[1]
SIDECAR_CONFIG = BACKEND.parent / "services" / "ml" / "ml_service" / "config.py"
SIDECAR_MODELS = SIDECAR_CONFIG.parent / "models.py"


def _vec(i: int = 0) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i % EMBEDDING_DIM] = 1.0
    return v


def _client(handler) -> MLClient:
    return MLClient("http://ml:8000", 5.0, transport=httpx.MockTransport(handler))


def _settings(**kw) -> Settings:
    base = dict(database_url="postgresql+asyncpg://u:p@h/db_test", postgres_password="p", secret_key="k")
    return Settings(**{**base, **kw})


# ── happy paths ─────────────────────────────────────────────────────────────

async def test_embed_posts_texts_and_returns_vectors():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["body"] = req.content
        return httpx.Response(200, json={"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM,
                                         "vectors": [_vec(0), _vec(1)]})

    vectors = await _client(handler).embed(["a", "b"])
    assert vectors == [_vec(0), _vec(1)]
    assert seen["url"] == "http://ml:8000/v1/embed"
    assert b'"texts":["a","b"]' in seen["body"].replace(b" ", b"")


async def test_embed_splits_large_lists_at_the_sidecar_limit():
    sizes = []

    def handler(req: httpx.Request):
        import json

        texts = json.loads(req.content)["texts"]
        sizes.append(len(texts))
        return httpx.Response(200, json={"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM,
                                         "vectors": [_vec(int(t)) for t in texts]})

    texts = [str(i) for i in range(MAX_EMBED_TEXTS + 44)]
    vectors = await _client(handler).embed(texts)
    assert sizes == [MAX_EMBED_TEXTS, 44]
    assert vectors == [_vec(i) for i in range(len(texts))]  # input order kept across batches


async def test_embed_empty_skips_the_network():
    def handler(req):
        raise AssertionError("no request expected")

    assert await _client(handler).embed([]) == []


async def test_ner_parses_entities():
    def handler(req):
        assert req.url.path == "/v1/ner"
        return httpx.Response(200, json={"ents": [{"text": "Borin", "label": "PERSON", "start": 0, "end": 5}]})

    assert await _client(handler).ner("Borin waves.") == [NamedEntity("Borin", "PERSON", 0, 5)]


async def test_status_parses():
    def handler(req):
        return httpx.Response(200, json={"models": [{"name": EMBEDDING_MODEL, "kind": "embedding",
                                                     "state": "loaded"}], "rss_bytes": 123})

    st = await _client(handler).status()
    assert st.rss_bytes == 123 and st.models[0].state == "loaded"


def _nli_body(n: int, offset: int = 0) -> dict:
    return {"scores": [{"entailment": (offset + i) / 1000, "neutral": 0.5,
                        "contradiction": 0.5 - (offset + i) / 1000} for i in range(n)]}


async def test_nli_posts_pairs_and_parses_scores():
    import json

    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"scores": [
            {"entailment": 0.001, "neutral": 0.001, "contradiction": 0.998}]})

    scores = await _client(handler).nli([("Mira died in the fire.", "Mira greeted the party.")])
    assert scores == [NliScores(entailment=0.001, neutral=0.001, contradiction=0.998)]
    assert seen["path"] == "/v1/nli"
    assert seen["body"] == {"pairs": [{"premise": "Mira died in the fire.",
                                       "hypothesis": "Mira greeted the party."}]}


async def test_nli_splits_at_the_sidecar_limit_and_keeps_order():
    import json

    sizes = []

    def handler(req: httpx.Request):
        pairs = json.loads(req.content)["pairs"]
        sizes.append(len(pairs))
        return httpx.Response(200, json=_nli_body(len(pairs), offset=int(pairs[0]["premise"])))

    pairs = [(str(i), "h") for i in range(MAX_NLI_PAIRS + 10)]
    scores = await _client(handler).nli(pairs)
    assert sizes == [MAX_NLI_PAIRS, 10]
    assert [round(s.entailment * 1000) for s in scores] == list(range(len(pairs)))


async def test_nli_empty_skips_the_network():
    def handler(req):
        raise AssertionError("no request expected")

    assert await _client(handler).nli([]) == []


@pytest.mark.parametrize("body", [
    {"scores": []},                                                          # count != pairs
    {"scores": [{"entailment": 1, "neutral": 0, "contradiction": 0}] * 2},
    {"scores": [{"entailment": 1.0, "neutral": 0.0}]},                       # missing key
    {"scores": [{"entailment": 1.0, "neutral": 0.0, "contradiction": 0.0, "x": 0.0}]},
    {"scores": [{"entailment": "1", "neutral": 0.0, "contradiction": 0.0}]},  # not a number
    {"scores": [{"entailment": True, "neutral": 0.0, "contradiction": 0.0}]},
    {"scores": [[1.0, 0.0, 0.0]]},
    {"scores": None},
    {},
    ["not", "an", "object"],
])
async def test_nli_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).nli([("p", "h")])
    _assert_terminal(info)


async def test_ocr_posts_multipart_file():
    seen = {}

    def handler(req: httpx.Request):
        seen["path"] = req.url.path
        seen["type"] = req.headers["content-type"]
        seen["body"] = req.content
        return httpx.Response(200, json={"text": "Mira died\nat the Silver Stag"})

    png = b"\x89PNG\r\n\x1a\nbody"
    assert await _client(handler).ocr(png, filename="page.png") == "Mira died\nat the Silver Stag"
    assert seen["path"] == "/v1/ocr"
    assert seen["type"].startswith("multipart/form-data; boundary=")
    assert b'name="file"; filename="page.png"' in seen["body"]
    assert png in seen["body"]


@pytest.mark.parametrize("body", [{"text": 3}, {"text": None}, {}, ["text"], {"text": ["a"]}])
async def test_ocr_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).ocr(b"x")
    _assert_terminal(info)


@pytest.mark.parametrize("status", [413, 422])
async def test_ocr_rejections_are_contract_errors(status):
    body = {"detail": "not a decodable image", "code": "invalid_image"}
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(status, json=body)).ocr(b"x")
    _assert_terminal(info)
    assert info.value.status_code == status


async def test_budget_503_is_unavailable_and_names_the_code():
    body = {"detail": "ml budget exceeded", "code": "ml_budget"}
    with pytest.raises(ModelServiceUnavailable) as info:
        await _client(lambda req: httpx.Response(503, json=body)).nli([("p", "h")])
    assert is_retryable(info.value)
    assert info.value.status_code == 503
    assert "ml_budget" in info.value.detail and "ml budget exceeded" in info.value.detail


async def test_status_parses_lazy_fields():
    def handler(req):
        return httpx.Response(200, json={
            "models": [{"name": EMBEDDING_MODEL, "kind": "embedding", "state": "loaded",
                        "lazy": False, "cost_mb": None},
                       {"name": "nli-deberta-v3-xsmall", "kind": "nli", "state": "not_loaded",
                        "lazy": True, "cost_mb": 600}],
            "resident_budget_mb": 2000, "lazy_resident_mb": 0, "rss_bytes": 5})

    st = await _client(handler).status()
    assert st.resident_budget_mb == 2000 and st.lazy_resident_mb == 0
    assert st.models[1].lazy and st.models[1].cost_mb == 600 and st.models[1].state == "not_loaded"
    assert not st.models[0].lazy and st.models[0].cost_mb is None


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
        await _client(handler).embed(["a"])
    assert is_retryable(info.value)


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_5xx_is_unavailable(status):
    with pytest.raises(ModelServiceUnavailable) as info:
        await _client(lambda req: httpx.Response(status, text="down")).ner("x")
    assert info.value.status_code == status


# ── contract break -> ModelServiceError (not retryable) ───────────────────

def _assert_terminal(info):
    assert type(info.value) is ModelServiceError
    assert not is_retryable(info.value)


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_4xx_is_contract_error(status):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(status, json={"detail": "bad"})).embed(["a"])
    _assert_terminal(info)
    assert info.value.status_code == status


@pytest.mark.parametrize("body", [
    {"model": EMBEDDING_MODEL, "dim": 768, "vectors": [_vec()]},               # wrong dim
    {"model": "all-mpnet-base-v2", "dim": EMBEDDING_DIM, "vectors": [_vec()]},  # wrong model
    {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "vectors": []},           # count != texts
    {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "vectors": [_vec(), _vec()]},
    {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM, "vectors": [[0.1, 0.2]]},  # short vector
    {"model": EMBEDDING_MODEL, "dim": EMBEDDING_DIM},                          # missing vectors
    ["not", "an", "object"],
])
async def test_embed_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).embed(["a"])
    _assert_terminal(info)


async def test_non_json_is_contract_error():
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, text="<html>")).ner("x")
    _assert_terminal(info)


@pytest.mark.parametrize("body", [{}, {"models": [{}], "rss_bytes": 1},
                                  {"models": [], "rss_bytes": "x"}, []])
async def test_status_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).status()
    _assert_terminal(info)


async def test_other_httpx_errors_stay_typed():
    def handler(req):
        raise httpx.DecodingError("bad gzip")

    with pytest.raises(ModelServiceError) as info:
        await _client(handler).ner("x")
    _assert_terminal(info)


@pytest.mark.parametrize("body", [{}, {"ents": [{"text": "x"}]}, {"ents": None}, []])
async def test_ner_contract_breaks(body):
    with pytest.raises(ModelServiceError) as info:
        await _client(lambda req: httpx.Response(200, json=body)).ner("x")
    _assert_terminal(info)


async def test_timeout_comes_from_settings():
    client = get_ml_client(_settings(environment="production", ml_url="http://ml:9000/", ml_timeout_s=7.5))
    assert isinstance(client, MLClient)
    assert client.base_url == "http://ml:9000"
    assert client.timeout_s == 7.5


# ── fake + selection ──────────────────────────────────────────────────────

def test_get_ml_client_selects_fake_under_test_env():
    assert isinstance(get_ml_client(_settings(environment="test")), FakeMLClient)
    assert isinstance(get_ml_client(_settings(environment="development")), MLClient)


def test_settings_defaults():
    s = _settings()
    assert s.ml_url == "http://ml:8000"
    assert s.ml_timeout_s == 30.0


async def test_fake_embeddings_are_stable_unit_vectors():
    fake = FakeMLClient()
    a1, b, a2 = await fake.embed(["alpha", "beta", "alpha"])
    assert a1 == a2 and a1 != b
    assert a1 == fake_vector("alpha")
    for v in (a1, b):
        assert len(v) == EMBEDDING_DIM
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)
    assert await fake.embed([]) == []


async def test_fake_ner_shape_and_order():
    text = "Borin Stonebeard swore to retrieve the ring of Moradin toward Waterdeep."
    ents = await FakeMLClient().ner(text)
    assert ents == fake_entities(text)
    for e in ents:
        assert text[e.start:e.end] == e.text
    labels = [e.label for e in ents]
    assert ("Borin Stonebeard", "PERSON") in [(e.text, e.label) for e in ents]
    assert ("Waterdeep", "GPE") in [(e.text, e.label) for e in ents]
    assert "ITEM" in labels and "QUEST" in labels
    first_rule = min(i for i, lab in enumerate(labels) if lab in ("ITEM", "QUEST"))
    assert all(lab not in ("ITEM", "QUEST") for lab in labels[:first_rule])
    assert all(lab in ("ITEM", "QUEST") for lab in labels[first_rule:])


async def test_fake_status():
    st = await FakeMLClient().status()
    assert {m.kind: m.state for m in st.models} == {
        "embedding": "loaded", "ner": "loaded", "nli": "not_loaded", "ocr": "not_loaded"}
    assert {m.kind for m in st.models if m.lazy} == {"nli", "ocr"}


async def test_fake_nli_is_stable_softmax_in_order():
    fake = FakeMLClient()
    pairs = [("Mira died.", "Mira lives."), ("a", "b"), ("Mira died.", "Mira lives.")]
    s1, s2, s3 = await fake.nli(pairs)
    assert s1 == s3 and s1 != s2
    assert s1 == fake_nli_scores(*pairs[0])
    for s in (s1, s2):
        assert math.isclose(s.entailment + s.neutral + s.contradiction, 1.0, rel_tol=1e-9)
    assert await fake.nli([]) == []
    with pytest.raises(ModelServiceError) as info:
        await fake.nli([("x" * 4001, "y")])
    assert info.value.status_code == 422


async def test_fake_ocr():
    fake = FakeMLClient()
    assert await fake.ocr(b"  Mira died  \n\n at the Silver Stag ") == "Mira died\nat the Silver Stag"
    assert await fake.ocr(b"\x89PNG\r\n\x1a\n\xff\xfe") == ""
    with pytest.raises(ModelServiceError) as info:
        await fake.ocr(b"")
    assert info.value.status_code == 422


# ── single embedding contract ─────────────────────────────────────────────

def _module_assignments(path: Path, name: str) -> list[ast.AST]:
    tree = ast.parse(path.read_text())
    out = []
    for n in tree.body:
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            out.append(n)
    return out


def test_embedding_constants_defined_once():
    hits = {name: [] for name in ("EMBEDDING_DIM", "EMBEDDING_MODEL")}
    literal_hits = []
    for path in (BACKEND / "app").rglob("*.py"):
        for name in hits:
            if _module_assignments(path, name):
                hits[name].append(path.relative_to(BACKEND).as_posix())
        if f'"{EMBEDDING_MODEL}"' in path.read_text():
            literal_hits.append(path.relative_to(BACKEND).as_posix())
    assert hits == {"EMBEDDING_DIM": ["app/domain/embedding.py"],
                    "EMBEDDING_MODEL": ["app/domain/embedding.py"]}
    assert literal_hits == ["app/domain/embedding.py"]


def test_models_and_service_use_the_contract():
    from app.db.models import journal, source
    from app.domain import embedding

    assert journal.EMBEDDING_DIM is embedding.EMBEDDING_DIM
    assert source.EMBEDDING_DIM is embedding.EMBEDDING_DIM
    assert journal.JournalEntry.__table__.c.embedding.type.dim == EMBEDDING_DIM
    assert source.SourceChunk.__table__.c.embedding.type.dim == EMBEDDING_DIM


@pytest.mark.skipif(not SIDECAR_CONFIG.exists(), reason="src/services/ml not in this checkout")
def test_sidecar_agrees_with_contract():
    values = {}
    for node in ast.parse(SIDECAR_CONFIG.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    values[t.id] = node.value.value
    assert values["EMBED_MODEL_NAME"] == EMBEDDING_MODEL
    assert values["EMBED_DIM"] == EMBEDDING_DIM
    assert values["MAX_EMBED_TEXTS"] == MAX_EMBED_TEXTS
    assert values["MAX_NLI_PAIRS"] == MAX_NLI_PAIRS


@pytest.mark.skipif(not SIDECAR_CONFIG.exists(), reason="src/services/ml not in this checkout")
def test_fake_limits_match_the_sidecar():
    from app.clients import fakes, ml

    assert _literal(SIDECAR_CONFIG, "MAX_NLI_CHARS") == fakes._MAX_NLI_CHARS
    assert _literal(SIDECAR_CONFIG, "MAX_OCR_BYTES") == fakes._MAX_OCR_BYTES
    assert ml.NLI_LABELS == _literal(SIDECAR_MODELS, "NLI_LABELS")


def _literal(path: Path, name: str):
    (node,) = _module_assignments(path, name)
    return ast.literal_eval(node.value)


@pytest.mark.skipif(not SIDECAR_MODELS.exists(), reason="src/services/ml not in this checkout")
@pytest.mark.parametrize("name", ["ITEM_PATTERNS", "QUEST_PATTERNS"])
def test_sidecar_matcher_patterns_match_nlp_service(name):
    """The sidecar copies these verbatim; tags would drift if either side changed alone."""
    nlp_service = BACKEND / "app" / "services" / "nlp_service.py"
    assert _literal(SIDECAR_MODELS, name) == _literal(nlp_service, name)
