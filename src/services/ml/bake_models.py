"""Build-time only: bake the sidecar's model weights into the image.

1. Download MiniLM at the pinned revision into ML_EMBED_MODEL_PATH
   (default /models/all-MiniLM-L6-v2) and verify model.safetensors against
   the sha256 in licenses/register.yaml.
2. Load both models once (MiniLM from that path, spaCy en_core_web_trf from
   its pip package) so a broken bake fails the build, not the first request.

The container then runs with HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from ml_service.config import (
    EMBED_DIM,
    EMBED_MODEL_REPO,
    EMBED_MODEL_REVISION,
    EMBED_MODEL_SHA256,
    load_config,
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    from huggingface_hub import snapshot_download

    from ml_service.models import SentenceTransformerEmbedder, SpacyNer

    cfg = load_config()
    target = Path(cfg.embed_model_path)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=EMBED_MODEL_REPO,
        revision=EMBED_MODEL_REVISION,
        local_dir=str(target),
        # Only what sentence-transformers needs on CPU; skips the ONNX /
        # OpenVINO / TF / Rust exports in the repo.
        allow_patterns=[
            "*.json", "*.txt", "model.safetensors", "1_Pooling/*", "2_Normalize/*",
        ],
    )
    weights = target / "model.safetensors"
    digest = sha256_of(weights)
    if digest != EMBED_MODEL_SHA256:
        print(f"model.safetensors sha256 {digest} != expected {EMBED_MODEL_SHA256}", file=sys.stderr)
        return 1

    vectors = SentenceTransformerEmbedder(str(target)).encode(["bake check"])
    if len(vectors) != 1 or len(vectors[0]) != EMBED_DIM:
        print(f"MiniLM returned an unexpected shape: {len(vectors)}x{len(vectors[0]) if vectors else 0}",
              file=sys.stderr)
        return 1
    SpacyNer(cfg.ner_model_name).extract("Borin Stonebeard walked to Waterdeep.")
    print(f"baked {EMBED_MODEL_REPO}@{EMBED_MODEL_REVISION} into {target}; {cfg.ner_model_name} loads")
    return 0


if __name__ == "__main__":
    sys.exit(main())
