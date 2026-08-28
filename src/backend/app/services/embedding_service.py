from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


def load_embedding_model() -> None:
    global _model
    _model = SentenceTransformer(EMBEDDING_MODEL)


def embed(text: str) -> list[float]:
    if _model is None:
        raise RuntimeError("Embedding model not loaded")
    return _model.encode(text, normalize_embeddings=True).tolist()
