"""
Evaluates the fine-tuned model against the validation set.
Runs inference via KoboldCpp and scores outputs.
Usage: python evaluate_model.py --validation ../data/processed/validation_set.jsonl --sample 50
"""
import argparse
import json
import random
import httpx
from pathlib import Path

KOBOLD_URL = "http://localhost:5001"


def generate(prompt: str, max_length: int = 400) -> str:
    payload = {
        "prompt": prompt,
        "max_length": max_length,
        "temperature": 0.72,
        "top_p": 0.95,
        "stop_sequence": ["\nInput:"],
    }
    response = httpx.post(f"{KOBOLD_URL}/api/v1/generate", json=payload, timeout=60)
    response.raise_for_status()
    return response.json()["results"][0]["text"].strip()


def score_output(reference: str, generated: str) -> dict:
    ref_words = set(reference.lower().split())
    gen_words = set(generated.lower().split())
    overlap = len(ref_words & gen_words) / max(len(ref_words), 1)
    return {
        "length": len(generated),
        "word_overlap": round(overlap, 3),
        "has_content": len(generated) > 100,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation", default="../data/processed/validation_set.jsonl")
    parser.add_argument("--sample", type=int, default=50)
    args = parser.parse_args()

    records = []
    with open(args.validation) as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    sample = random.sample(records, min(args.sample, len(records)))
    print(f"Evaluating {len(sample)} samples...\n")

    scores = []
    for i, record in enumerate(sample):
        prompt = f"{record['instruction']}\n\nInput: {record['input']}\nOutput:"
        try:
            generated = generate(prompt)
            score = score_output(record["output"], generated)
            scores.append(score)
            print(f"[{i+1}/{len(sample)}] length={score['length']} overlap={score['word_overlap']}")
        except Exception as e:
            print(f"[{i+1}/{len(sample)}] ERROR: {e}")

    if scores:
        avg_length = sum(s["length"] for s in scores) / len(scores)
        avg_overlap = sum(s["word_overlap"] for s in scores) / len(scores)
        has_content_pct = sum(1 for s in scores if s["has_content"]) / len(scores) * 100
        print(f"\n--- Results ---")
        print(f"Avg output length: {avg_length:.0f} chars")
        print(f"Avg word overlap with reference: {avg_overlap:.3f}")
        print(f"Outputs with content (>100 chars): {has_content_pct:.1f}%")


if __name__ == "__main__":
    main()
