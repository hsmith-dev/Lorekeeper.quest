"""HTTP contract of the sidecar, against fake models (the I/O matrix rows)."""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from ml_service.app import create_app, rss_bytes
from ml_service.config import MAX_EMBED_TEXTS, Config, load_config

PKG = Path(__file__).resolve().parents[1] / "ml_service"


def test_healthz_ok_once_loaded(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_healthz_503_before_load():
    app = create_app(Config(), embedder_factory=lambda c: None, ner_factory=lambda c: None)
    c = TestClient(app)  # no context manager: lifespan never runs, nothing loads
    assert c.get("/healthz").status_code == 503


def test_lifespan_failure_propagates():
    def boom(c):
        raise RuntimeError("no weights")

    app = create_app(Config(), embedder_factory=boom, ner_factory=lambda c: None)
    try:
        with TestClient(app):
            pass
    except RuntimeError as exc:
        assert "no weights" in str(exc)
    else:
        raise AssertionError("startup should fail when a model cannot load")
    assert app.state.slots[0].state == "failed"


def test_embed_returns_unit_vectors_in_order(client, fake_embedder):
    r = client.post("/v1/embed", json={"texts": ["a", "b"]})
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "all-MiniLM-L6-v2"
    assert body["dim"] == 384
    assert len(body["vectors"]) == 2
    for v in body["vectors"]:
        assert len(v) == 384
        assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)
    # Input order preserved: each vector is the one for its own text.
    assert body["vectors"] == fake_embedder.encode(["a", "b"])
    assert body["vectors"][0] != body["vectors"][1]


def test_embed_empty(client, fake_embedder):
    r = client.post("/v1/embed", json={"texts": []})
    assert r.status_code == 200
    assert r.json() == {"model": "all-MiniLM-L6-v2", "dim": 384, "vectors": []}
    assert fake_embedder.calls == []  # the model is never invoked for nothing


def test_embed_limit(client):
    ok = client.post("/v1/embed", json={"texts": ["x"] * MAX_EMBED_TEXTS})
    assert ok.status_code == 200
    assert len(ok.json()["vectors"]) == MAX_EMBED_TEXTS
    assert client.post("/v1/embed", json={"texts": ["x"] * (MAX_EMBED_TEXTS + 1)}).status_code == 422


def test_embed_bad_body(client):
    assert client.post("/v1/embed", json={}).status_code == 422
    assert client.post("/v1/embed", json={"texts": "a"}).status_code == 422
    assert client.post("/v1/embed", json={"texts": [1, 2]}).status_code == 422


def test_ner_offsets_and_order(client):
    text = "Borin found a ring of Fire."
    r = client.post("/v1/ner", json={"text": text})
    assert r.status_code == 200
    ents = r.json()["ents"]
    assert [e["label"] for e in ents] == ["PERSON", "PERSON", "ITEM"]  # spaCy ents first, then Matcher
    for e in ents:
        assert set(e) == {"text", "label", "start", "end"}
        assert text[e["start"]:e["end"]] == e["text"]


def test_ner_bad_body(client):
    assert client.post("/v1/ner", json={}).status_code == 422


def test_status(client):
    r = client.get("/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == [
        {"name": "all-MiniLM-L6-v2", "kind": "embedding", "state": "loaded"},
        {"name": "en_core_web_trf", "kind": "ner", "state": "loaded"},
    ]
    assert isinstance(body["rss_bytes"], int) and body["rss_bytes"] > 0


def test_rss_bytes_positive():
    assert rss_bytes() > 0


def test_config_from_env():
    cfg = load_config({"ML_EMBED_MODEL_PATH": "/tmp/minilm", "ML_NER_MODEL": "en_core_web_sm"})
    assert cfg.embed_model_path == "/tmp/minilm"
    assert cfg.ner_model_name == "en_core_web_sm"
    assert load_config({}).embed_model_path == "/models/all-MiniLM-L6-v2"


def test_no_backend_or_heavy_imports_at_module_level():
    """ml_service never imports `app`, and only the loaders import the ML stack."""
    heavy = {"torch", "sentence_transformers", "spacy", "transformers"}
    for path in PKG.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            assert "app" not in names, f"{path.name} imports the backend app package"
        for node in tree.body:  # module level only
            if isinstance(node, ast.Import):
                assert not {a.name.split(".")[0] for a in node.names} & heavy, path.name
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in heavy, path.name


def test_importing_app_loads_no_models():
    for mod in ("torch", "sentence_transformers", "spacy"):
        if mod in sys.modules:
            continue  # already imported by another test (e.g. test_nlp); nothing to assert
        import ml_service.app  # noqa: F401

        assert mod not in sys.modules
