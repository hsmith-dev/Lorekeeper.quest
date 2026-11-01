"""Model interfaces, the real loaders, and the per-model slots the app serves.

torch / sentence_transformers / spacy / transformers / rapidocr / PIL /
numpy are imported only inside the real loader and reader classes below,
never at module import time, so the HTTP app runs (and is tested) with fakes.
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


NLI_LABELS = ("entailment", "neutral", "contradiction")


class NliModel(Protocol):
    def score(self, pairs: Sequence[tuple[str, str]]) -> list[dict[str, float]]:
        """One {entailment, neutral, contradiction} softmax per (premise,
        hypothesis) pair, in input order. The app calls it per chunk of
        ML_NLI_BATCH_SIZE pairs."""


class OcrModel(Protocol):
    def read(self, image_bytes: bytes) -> str:
        """The image's text: stripped non-empty lines joined with "\\n".
        Raises InvalidImage when the bytes are not a decodable image."""


class InvalidImage(ValueError):
    """The upload is empty or not an image PIL can decode (422)."""


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


class TransformersNli:
    """cross-encoder/nli-deberta-v3-xsmall from the path baked at image build.

    Label order comes from the model's config.id2label (for this checkpoint
    0 contradiction, 1 entailment, 2 neutral), never from a hard-coded list.
    """

    def __init__(self, path: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(path)
        self._model = AutoModelForSequenceClassification.from_pretrained(path)
        self._model.eval()
        id2label = self._model.config.id2label
        self._labels = [str(id2label[i]).lower() for i in range(len(id2label))]
        if sorted(self._labels) != sorted(NLI_LABELS):
            raise ValueError(f"{path}: id2label {id2label!r} is not {NLI_LABELS}")

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[dict[str, float]]:
        if not pairs:
            return []
        enc = self._tokenizer(
            [p for p, _ in pairs], [h for _, h in pairs],
            padding=True, truncation=True, return_tensors="pt",
        )
        with self._torch.inference_mode():
            logits = self._model(**enc).logits
        probs = self._torch.softmax(logits.float(), dim=-1).tolist()
        return [dict(zip(self._labels, row)) for row in probs]


class RapidOcrReader:
    """RapidOCR (PP-OCRv6 small, onnxruntime) from the .onnx files baked into
    model_dir. Every model is passed by path, so RapidOCR never downloads.

    read(): PIL decode, EXIF orientation applied (phone photos), convert("RGB"),
    then RapidOCR's text lines (top to bottom), stripped, empty ones dropped,
    joined with "\\n": the rule the backend's EasyOCR vision_service had.
    `engine` is injectable for tests.
    """

    def __init__(self, model_dir: str, engine: object | None = None):
        if engine is None:
            from pathlib import Path

            from rapidocr import RapidOCR

            from ml_service.config import OCR_CLS_FILE, OCR_DET_FILE, OCR_REC_FILE

            d = Path(model_dir)
            params: dict[str, object] = {
                "Global.log_level": "warning",
                "Det.model_path": str(d / OCR_DET_FILE),
                "Cls.model_path": str(d / OCR_CLS_FILE),
                "Rec.model_path": str(d / OCR_REC_FILE),
            }
            for key in ("Det.model_path", "Cls.model_path", "Rec.model_path"):
                if not Path(str(params[key])).is_file():
                    raise FileNotFoundError(f"{params[key]} (baked by bake_models.py) is missing")
            engine = RapidOCR(params=params)
        self._engine = engine

    def read(self, image_bytes: bytes) -> str:
        import io

        from PIL import Image, ImageOps

        if not image_bytes:
            raise InvalidImage("empty upload")
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image = (ImageOps.exif_transpose(image) or image).convert("RGB")
        except (OSError, EOFError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            # UnidentifiedImageError and truncated files are OSErrors.
            raise InvalidImage(f"not a decodable image: {type(exc).__name__}") from exc
        result = self._engine(image)
        lines = getattr(result, "txts", None) or ()
        return "\n".join(line.strip() for line in lines if line and line.strip())


class ModelSlot:
    """One served model, with its own lock.

    The lock serialises both loading and inference for this model, so two
    requests never run the same torch/spaCy pipeline concurrently, while an
    embed and an NER call can still run side by side. Resident slots
    (embeddings, NER) load in the lifespan; budget.LazySlot adds load on
    first use and eviction under the resident-memory budget.
    """

    lazy = False
    cost_mb: int | None = None  # resident models are outside the lazy budget

    def __init__(self, name: str, kind: str, loader: Callable[[], object]):
        self.name = name
        self.kind = kind
        self._loader = loader
        self._model: object | None = None
        self.state = "not_loaded"  # not_loaded | loading | loaded | failed
        self.error: str | None = None
        self.lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

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

    def unload(self) -> None:
        """Drop the model reference (state back to not_loaded). The caller
        makes sure nothing is serving from it; freeing the memory is
        budget.release_memory()'s job once the last reference is gone."""
        with self.lock:
            self._model = None
            self.state = "not_loaded"
            self.error = None
