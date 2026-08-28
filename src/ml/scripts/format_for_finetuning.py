"""
Converts reviewed JSONL (with output populated) into train/validation splits
in Alpaca format ready for Unsloth.
Usage: python format_for_finetuning.py --input-dir ../data/raw --output-dir ../data/processed --train-split 0.75
"""
import argparse
import json
import random
from pathlib import Path


def format_alpaca(record: dict) -> dict:
    return {
        "instruction": record["instruction"],
        "input": record["input"],
        "output": record["output"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="../data/raw")
    parser.add_argument("--output-dir", default="../data/processed")
    parser.add_argument("--train-split", type=float, default=0.75)
    args = parser.parse_args()

    all_records = []
    for path in Path(args.input_dir).glob("*.jsonl"):
        with open(path) as f:
            for line in f:
                record = json.loads(line)
                if record.get("output", "").strip():  # only include completed pairs
                    all_records.append(format_alpaca(record))

    random.shuffle(all_records)
    split_idx = int(len(all_records) * args.train_split)
    train = all_records[:split_idx]
    val = all_records[split_idx:]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "training_set.jsonl", "w") as f:
        for r in train:
            f.write(json.dumps(r) + "\n")

    with open(out_dir / "validation_set.jsonl", "w") as f:
        for r in val:
            f.write(json.dumps(r) + "\n")

    print(f"Train: {len(train)} | Validation: {len(val)}")


if __name__ == "__main__":
    main()
