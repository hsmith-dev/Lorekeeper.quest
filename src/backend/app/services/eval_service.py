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
    return {
        "length": len(generated),
        "word_overlap": overlap,
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
            "has_content_pct": 0.0, "error_count": errors,
        }

    return {
        "sample_size": len(sample),
        "avg_length": sum(s["length"] for s in scores) / len(scores),
        "avg_word_overlap": sum(s["word_overlap"] for s in scores) / len(scores),
        "has_content_pct": sum(1 for s in scores if s["has_content"]) / len(scores) * 100,
        "error_count": errors,
    }
