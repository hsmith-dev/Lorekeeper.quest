from sentence_transformers import SentenceTransformer

from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL  # noqa: F401 (re-exported)

_model: SentenceTransformer | None = None


def load_embedding_model() -> None:
    global _model
    _model = SentenceTransformer(EMBEDDING_MODEL)


def embed(text: str) -> list[float]:
    if _model is None:
        raise RuntimeError("Embedding model not loaded")
    return _model.encode(text, normalize_embeddings=True).tolist()
