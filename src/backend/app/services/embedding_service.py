"""Embeddings through the `ml` sidecar (E0-Platform.6).

The backend loads no model: embed() / embed_many() call /v1/embed on the
ml sidecar (app/clients/ml.py), which serves the same MiniLM the backend
used to load in-process. Failures surface as ModelServiceError /
ModelServiceUnavailable (app/clients/errors.py); each caller decides
whether that degrades (journal save, retrieval) or is a 503 (source
upload, reindex).

Scripts can swap the client: `use_client(obj)` installs any object with an
`async embed(texts) -> list[list[float]]` (the eval's bag-of-words fake, a
disabled client for `--embeddings skip`); `use_client(None)` restores
get_ml_client().
"""

from __future__ import annotations

from typing import Any

from app.clients.ml import get_ml_client
from app.domain.embedding import EMBEDDING_DIM, EMBEDDING_MODEL  # noqa: F401 (re-exported)

_override: Any | None = None


def use_client(client: Any | None) -> None:
    """Install an embedding client override (None restores the default)."""
    global _override
    _override = client


def current_client() -> Any:
    return _override if _override is not None else get_ml_client()


async def embed_many(texts: list[str]) -> list[list[float]]:
    """Unit vectors in input order (the ml client batches per 256 texts)."""
    texts = list(texts)
    if not texts:
        return []
    return await current_client().embed(texts)


async def embed(text: str) -> list[float]:
    return (await embed_many([text]))[0]
