"""
Validates a JSONL dataset for completeness and quality before fine-tuning.
Usage: python validate_dataset.py --input ../data/processed/training_set.jsonl
"""
import argparse
import json
from pathlib import Path


def validate_record(record: dict, idx: int) -> list[str]:
    errors = []
    if not record.get("instruction", "").strip():
        errors.append(f"Record {idx}: missing instruction")
    if not record.get("input", "").strip():
        errors.append(f"Record {idx}: missing input")
    if not record.get("output", "").strip():
        errors.append(f"Record {idx}: missing output")
    if len(record.get("output", "")) < 100:
        errors.append(f"Record {idx}: output too short ({len(record.get('output', ''))} chars)")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"File not found: {path}")
        return

    all_errors = []
    total = 0
    with open(path) as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            total += 1
            try:
                record = json.loads(line)
                all_errors.extend(validate_record(record, idx))
            except json.JSONDecodeError as e:
                all_errors.append(f"Record {idx}: invalid JSON — {e}")

    print(f"Validated {total} records")
    if all_errors:
        print(f"{len(all_errors)} errors found:")
        for err in all_errors[:20]:
            print(f"  {err}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more")
    else:
        print("All records valid.")


if __name__ == "__main__":
    main()
