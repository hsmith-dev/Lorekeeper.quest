"""Build-time only: bake the sidecar's model weights into the image.

1. Download MiniLM at the pinned revision into ML_EMBED_MODEL_PATH
   (default /models/all-MiniLM-L6-v2) and verify model.safetensors against
   the sha256 in licenses/register.yaml.
2. Download nli-deberta-v3-xsmall at the pinned revision into
   ML_NLI_MODEL_PATH (default /models/nli-deberta-v3-xsmall), same check.
3. Download the EasyOCR "en" zips (CRAFT detector, english_g2 recogniser),
   verify each zip's sha256, and extract the .pth files into ML_OCR_MODEL_DIR
   (default /models/easyocr).
4. Load every model once (MiniLM, spaCy en_core_web_trf from its pip
   package, NLI, OCR) so a broken bake fails the build, not the first
   request. NLI must call the CPU spike's Mira pair a contradiction; the OCR
   output for a rendered text image is printed.

The container then runs with HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1, and
EasyOCR is built with download_enabled=False.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from ml_service.config import (
    EMBED_DIM,
    EMBED_MODEL_REPO,
    EMBED_MODEL_REVISION,
    EMBED_MODEL_SHA256,
    NLI_MODEL_REPO,
    NLI_MODEL_REVISION,
    NLI_MODEL_SHA256,
    OCR_ZIPS,
    load_config,
)

# From _bmad-output/planning-artifacts/spikes/cpu-benchmarks.md (p ~ 0.998).
MIRA_PAIR = ("Mira died in the fire at the Silver Stag.", "Mira greeted the party at the inn the next morning.")
OCR_CHECK_TEXT = "Lorekeeper bake check"


class BakeError(Exception):
    pass


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_sha(path: Path, expected: str) -> None:
    digest = sha256_of(path)
    if digest != expected:
        raise BakeError(f"{path.name} sha256 {digest} != expected {expected}")


def bake_hf(repo: str, revision: str, sha256: str, target: Path, allow_patterns: list[str]) -> None:
    from huggingface_hub import snapshot_download

    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=repo, revision=revision, local_dir=str(target), allow_patterns=allow_patterns)
    _check_sha(target / "model.safetensors", sha256)


def bake_ocr(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for url, sha256 in OCR_ZIPS:
            archive = Path(tmp) / url.rsplit("/", 1)[1]
            with urllib.request.urlopen(url, timeout=300) as resp, archive.open("wb") as out:
                shutil.copyfileobj(resp, out)
            _check_sha(archive, sha256)
            with zipfile.ZipFile(archive) as zf:
                members = [m for m in zf.infolist() if m.filename.endswith(".pth") and not m.is_dir()]
                if not members:
                    raise BakeError(f"{archive.name} holds no .pth file")
                for m in members:
                    # Flatten: EasyOCR looks for <model_storage_directory>/<name>.pth.
                    with zf.open(m) as src, (target / Path(m.filename).name).open("wb") as dst:
                        shutil.copyfileobj(src, dst)


def _text_png(text: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.load_default(size=48)
    except TypeError:  # Pillow without FreeType sizing
        font = ImageFont.load_default()
    image = Image.new("RGB", (900, 120), "white")
    ImageDraw.Draw(image).text((20, 30), text, fill="black", font=font)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    from ml_service.models import EasyOcrReader, SentenceTransformerEmbedder, SpacyNer, TransformersNli

    cfg = load_config()
    embed_dir, nli_dir, ocr_dir = Path(cfg.embed_model_path), Path(cfg.nli_model_path), Path(cfg.ocr_model_dir)
    try:
        bake_hf(
            EMBED_MODEL_REPO, EMBED_MODEL_REVISION, EMBED_MODEL_SHA256, embed_dir,
            # Only what sentence-transformers needs on CPU; skips the ONNX /
            # OpenVINO / TF / Rust exports in the repo.
            ["*.json", "*.txt", "model.safetensors", "1_Pooling/*", "2_Normalize/*"],
        )
        # tokenizer.json is the fast tokenizer; spm.model is its source. Skips
        # pytorch_model.bin and the ONNX exports.
        bake_hf(NLI_MODEL_REPO, NLI_MODEL_REVISION, NLI_MODEL_SHA256, nli_dir,
                ["*.json", "spm.model", "model.safetensors"])
        bake_ocr(ocr_dir)
    except BakeError as exc:
        print(exc, file=sys.stderr)
        return 1

    vectors = SentenceTransformerEmbedder(str(embed_dir)).encode(["bake check"])
    if len(vectors) != 1 or len(vectors[0]) != EMBED_DIM:
        print(f"MiniLM returned an unexpected shape: {len(vectors)}x{len(vectors[0]) if vectors else 0}",
              file=sys.stderr)
        return 1
    SpacyNer(cfg.ner_model_name).extract("Borin Stonebeard walked to Waterdeep.")

    (scores,) = TransformersNli(str(nli_dir)).score([MIRA_PAIR])
    verdict = max(scores, key=scores.get)
    print(f"NLI {MIRA_PAIR}: {scores}")
    if verdict != "contradiction":
        print(f"NLI called the Mira pair {verdict!r}, expected 'contradiction'", file=sys.stderr)
        return 1

    text = EasyOcrReader(str(ocr_dir)).read(_text_png(OCR_CHECK_TEXT))
    print(f"OCR of a rendered {OCR_CHECK_TEXT!r}: {text!r}")

    print(f"baked {EMBED_MODEL_REPO}@{EMBED_MODEL_REVISION} into {embed_dir}; "
          f"{NLI_MODEL_REPO}@{NLI_MODEL_REVISION} into {nli_dir}; EasyOCR en into {ocr_dir}; "
          f"{cfg.ner_model_name}, NLI and OCR load")
    return 0


if __name__ == "__main__":
    sys.exit(main())
