"""Runs the validation set against a configured LLM provider and scores the
output — the in-app counterpart to src/ml/scripts/evaluate_model.py, using the
same word-overlap scoring, but routed through llm_provider.complete_messages
so it works with any configured provider, not just KoboldCpp's native API."""

import json
import random
from pathlib import Path

from app.services.llm_provider import LLMConfig, complete_messages

VALIDATION_SET_PATH = Path(__file__).resolve().parents[3] / "ml" / "data" / "processed" / "validation_set.jsonl"


def _load_validation_set() -> list[dict]:
    if not VALIDATION_SET_PATH.exists():
        return []
    records = []
    with open(VALIDATION_SET_PATH) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    return records


def _score(reference: str, generated: str) -> dict:
    ref_words = set(reference.lower().split())
    gen_words = set(generated.lower().split())
    overlap = len(ref_words & gen_words) / max(len(ref_words), 1)
    # Word overlap is kept for continuity with older stored runs, but it's a
    # weak metric: it rewards verbosity (more words → more chance of overlap)
    # and is blind to meaning ("the dragon slew the knight" vs "the knight
    # slew the dragon" score identically). Semantic similarity — cosine
    # similarity of sentence-transformer embeddings, the same encoder that
    # powers RAG retrieval — measures whether the generation *means* what the
    # reference means, which is what the fine-tune is actually for.
    semantic = 0.0
    try:
        from app.services.embedding_service import embed
        ref_vec = embed(reference)
        gen_vec = embed(generated)
        dot = sum(a * b for a, b in zip(ref_vec, gen_vec))
        norm_r = sum(a * a for a in ref_vec) ** 0.5
        norm_g = sum(b * b for b in gen_vec) ** 0.5
        if norm_r and norm_g:
            semantic = dot / (norm_r * norm_g)
    except Exception:
        pass  # scoring must not fail an eval run over an embedding hiccup
    return {
        "length": len(generated),
        "word_overlap": overlap,
        "semantic_similarity": semantic,
        "has_content": len(generated) > 100,
    }


async def run_evaluation(config: LLMConfig, sample_size: int) -> dict:
    records = _load_validation_set()
    if not records:
        raise FileNotFoundError(
            f"No validation set found at {VALIDATION_SET_PATH}. Run "
            "src/ml/scripts/format_for_finetuning.py first."
        )

    sample = random.sample(records, min(sample_size, len(records)))
    scores = []
    errors = 0

    # 90s, not 60s: a cold Ollama model load alone took ~60s for a 7B Q4
    # model on the production ARM host (confirmed live) — only the first
    # sample in a run actually pays this (OLLAMA_KEEP_ALIVE keeps it loaded
    # for the rest), but that first sample needs enough runway for the load
    # *and* the generation on top of it.
    for record in sample:
        messages = [
            {"role": "system", "content": record["instruction"]},
            {"role": "user", "content": f"Input: {record['input']}\nOutput:"},
        ]
        try:
            generated = await complete_messages(messages, config, max_tokens=400, timeout=90)
            scores.append(_score(record["output"], generated))
        except Exception:
            errors += 1

    if not scores:
        return {
            "sample_size": len(sample), "avg_length": 0.0, "avg_word_overlap": 0.0,
            "avg_semantic_similarity": 0.0, "has_content_pct": 0.0, "error_count": errors,
        }

    return {
        "sample_size": len(sample),
        "avg_length": sum(s["length"] for s in scores) / len(scores),
        "avg_word_overlap": sum(s["word_overlap"] for s in scores) / len(scores),
        "avg_semantic_similarity": sum(s["semantic_similarity"] for s in scores) / len(scores),
        "has_content_pct": sum(1 for s in scores if s["has_content"]) / len(scores) * 100,
        "error_count": errors,
    }
