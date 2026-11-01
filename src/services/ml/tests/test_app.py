"""HTTP contract of the sidecar, against fake models (the I/O matrix rows)."""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from ml_service.app import create_app, rss_bytes
from ml_service.config import MAX_EMBED_TEXTS, MAX_NER_CHARS, Config, load_config

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


def test_ner_length_limit(client):
    assert client.post("/v1/ner", json={"text": "a" * MAX_NER_CHARS}).status_code == 200
    assert client.post("/v1/ner", json={"text": "a" * (MAX_NER_CHARS + 1)}).status_code == 422


def test_status(client):
    r = client.get("/v1/status")
    assert r.status_code == 200
    body = r.json()
    assert body["models"] == [
        {"name": "all-MiniLM-L6-v2", "kind": "embedding", "state": "loaded", "lazy": False, "cost_mb": None},
        {"name": "en_core_web_trf", "kind": "ner", "state": "loaded", "lazy": False, "cost_mb": None},
        {"name": "nli-deberta-v3-xsmall", "kind": "nli", "state": "not_loaded", "lazy": True, "cost_mb": 600},
        {"name": "easyocr-en", "kind": "ocr", "state": "not_loaded", "lazy": True, "cost_mb": 900},
    ]
    assert body["resident_budget_mb"] == 2000
    assert body["lazy_resident_mb"] == 0
    assert isinstance(body["rss_bytes"], int) and body["rss_bytes"] > 0


def test_rss_bytes_positive():
    assert rss_bytes() > 0


def test_config_from_env():
    cfg = load_config({"ML_EMBED_MODEL_PATH": "/tmp/minilm", "ML_NER_MODEL": "en_core_web_sm"})
    assert cfg.embed_model_path == "/tmp/minilm"
    assert cfg.ner_model_name == "en_core_web_sm"
    assert load_config({}).embed_model_path == "/models/all-MiniLM-L6-v2"


def test_lazy_config_from_env():
    cfg = load_config({})
    assert (cfg.resident_budget_mb, cfg.nli_cost_mb, cfg.ocr_cost_mb, cfg.nli_batch_size) == (2000, 600, 900, 32)
    assert cfg.nli_model_path == "/models/nli-deberta-v3-xsmall"
    assert cfg.ocr_model_dir == "/models/easyocr"
    cfg = load_config({"ML_RESIDENT_BUDGET_MB": "1500", "ML_NLI_COST_MB": "1200", "ML_OCR_COST_MB": "1000",
                       "ML_NLI_BATCH_SIZE": "8", "ML_NLI_MODEL_PATH": "/m/nli", "ML_OCR_MODEL_DIR": "/m/ocr"})
    assert (cfg.resident_budget_mb, cfg.nli_cost_mb, cfg.ocr_cost_mb, cfg.nli_batch_size) == (1500, 1200, 1000, 8)
    assert (cfg.nli_model_path, cfg.ocr_model_dir) == ("/m/nli", "/m/ocr")
    try:
        load_config({"ML_NLI_BATCH_SIZE": "0"})
    except ValueError:
        pass
    else:
        raise AssertionError("a zero batch size would loop forever")


def test_no_backend_or_heavy_imports_at_module_level():
    """ml_service never imports `app`, and only the loaders import the ML stack."""
    heavy = {"torch", "sentence_transformers", "spacy", "transformers", "easyocr", "PIL", "numpy", "cv2"}
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
    for mod in ("torch", "sentence_transformers", "spacy", "transformers", "easyocr"):
        if mod in sys.modules:
            continue  # already imported by another test (e.g. test_nlp); nothing to assert
        import ml_service.app  # noqa: F401

        assert mod not in sys.modules
