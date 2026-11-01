"""Model interfaces, the real loaders, and the per-model slots the app serves.

torch / sentence_transformers / spacy are imported only inside the real
loader classes below, never at module import time.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

# Copied verbatim from src/backend/app/services/nlp_service.py (the sidecar
# must not import the backend). Keep the two in step until E0-Platform.6
# moves the callers over and the backend copy goes away.
ITEM_PATTERNS = [
    [{"TEXT": {"REGEX": r"^\+\d$"}}, {"POS": {"IN": ["NOUN", "PROPN"]}}],
    [{"LOWER": {"IN": ["ring", "wand", "staff", "amulet", "sword", "dagger", "bow", "shield", "armor"]}},
     {"LOWER": "of"}, {"POS": {"IN": ["NOUN", "PROPN"]}, "OP": "+"}],
]

QUEST_PATTERNS = [
    [{"LOWER": {"IN": ["defeat", "find", "retrieve", "escort", "destroy", "investigate", "survive"]}},
     {"POS": {"IN": ["DET", "NOUN", "PROPN", "ADJ"]}, "OP": "*"},
     {"POS": {"IN": ["NOUN", "PROPN"]}}],
]


@dataclass(frozen=True)
class Entity:
    text: str
    label: str
    start: int  # character offsets into the request text: text[start:end] == self.text
    end: int


class Embedder(Protocol):
    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        """Unit-norm vectors, one per text, in input order."""


class NerModel(Protocol):
    def extract(self, text: str) -> list[Entity]:
        """spaCy entities first, then Matcher ITEM/QUEST spans."""


class SentenceTransformerEmbedder:
    """MiniLM from the path baked at image build (offline at runtime)."""

    def __init__(self, path: str, batch_size: int = 32):
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(path, device="cpu")
        self._batch_size = batch_size

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


class SpacyNer:
    """spaCy transformer NER plus the ITEM/QUEST Matcher."""

    def __init__(self, model_name: str):
        import spacy
        from spacy.matcher import Matcher

        self._nlp = spacy.load(model_name)
        self._matcher = Matcher(self._nlp.vocab)
        self._matcher.add("ITEM", ITEM_PATTERNS)
        self._matcher.add("QUEST", QUEST_PATTERNS)

    def extract(self, text: str) -> list[Entity]:
        doc = self._nlp(text)
        ents = [Entity(e.text, e.label_, e.start_char, e.end_char) for e in doc.ents]
        for match_id, start, end in self._matcher(doc):
            span = doc[start:end]
            ents.append(Entity(span.text, self._nlp.vocab.strings[match_id],
                               span.start_char, span.end_char))
        return ents


class ModelSlot:
    """One served model: lazy-loadable, with its own lock.

    The lock serialises both loading and inference for this model, so two
    requests never run the same torch/spaCy pipeline concurrently, while an
    embed and an NER call can still run side by side.
    """

    def __init__(self, name: str, kind: str, loader: Callable[[], object]):
        self.name = name
        self.kind = kind
        self._loader = loader
        self._model: object | None = None
        self.state = "unloaded"  # unloaded | loading | loaded | failed
        self.error: str | None = None
        self.lock = threading.Lock()

    def _ensure_loaded(self) -> object:
        # Caller holds self.lock.
        if self._model is None:
            self.state = "loading"
            try:
                self._model = self._loader()
            except Exception as exc:
                self.state = "failed"
                self.error = f"{type(exc).__name__}: {exc}"
                raise
            self.state = "loaded"
            self.error = None
        return self._model

    def load(self) -> None:
        with self.lock:
            self._ensure_loaded()

    def run(self, fn: Callable[[object], object]) -> object:
        with self.lock:
            return fn(self._ensure_loaded())
