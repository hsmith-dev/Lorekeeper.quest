"""Build-time only: bake the sidecar's speech model into the image.

1. Download Systran/faster-whisper-base at the pinned revision (config.json,
   model.bin, tokenizer.json, vocabulary.txt) into STT_MODEL_PATH (default
   /models/faster-whisper-base) and verify model.bin against the sha256 in
   licenses/register.yaml.
2. Encode 1 s of a 440 Hz tone to webm/ogg (libopus), mp3 (libmp3lame), wav
   (pcm_s16le) and mp4 (aac) with the `ffmpeg` CLI, and check decode_container
   turns each back into ~16000 float32 samples: the real container path (the
   ffmpeg subprocess), on real encoded audio.
3. Load the model once with the configured STT_COMPUTE_TYPE and transcribe 1 s
   of silence, so a broken bake fails the build, not the first request.

The container then runs with HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from stt_service.config import (
    MODEL_FILES,
    MODEL_REPO,
    MODEL_REVISION,
    MODEL_SHA256,
    SAMPLE_RATE,
    load_config,
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# (container format, encoder) pairs the browser / users actually upload.
DECODE_CHECKS = (("webm", "libopus"), ("ogg", "libopus"), ("mp3", "libmp3lame"), ("wav", "pcm_s16le"),
                 ("mp4", "aac"))


def encode_tone(fmt: str, codec: str, seconds: float = 1.0, rate: int = 48000, hz: float = 440.0,
                ffmpeg: str = "ffmpeg") -> bytes:
    """`seconds` of a sine tone, encoded by the `ffmpeg` CLI (a subprocess, like decoding)."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / f"tone.{fmt}"
        subprocess.run(
            [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", f"sine=frequency={hz}:sample_rate={rate}:duration={seconds}",
             "-ac", "1", "-c:a", codec, "-f", fmt, str(out)],
            check=True, capture_output=True, timeout=60,
        )
        return out.read_bytes()


def check_container_decode(decoder=None) -> list[str]:
    """Problems found (empty = fine) decoding each DECODE_CHECKS clip: each
    must come back as float32 with 16000 samples, give or take 10%."""
    import numpy as np

    if decoder is None:
        from stt_service.models import decode_container as decoder

    problems = []
    for fmt, codec in DECODE_CHECKS:
        try:
            samples = decoder(encode_tone(fmt, codec))
        except Exception as exc:
            problems.append(f"{fmt}/{codec}: {type(exc).__name__}: {exc}")
            continue
        if not isinstance(samples, np.ndarray) or samples.dtype != np.float32:
            problems.append(f"{fmt}/{codec}: decoded to {type(samples).__name__} "
                            f"{getattr(samples, 'dtype', '')}, expected float32")
        elif abs(len(samples) - SAMPLE_RATE) > SAMPLE_RATE * 0.1:
            problems.append(f"{fmt}/{codec}: {len(samples)} samples, expected ~{SAMPLE_RATE}")
    return problems


def main() -> int:
    import numpy as np
    from huggingface_hub import snapshot_download

    from stt_service.models import FasterWhisperModel

    cfg = load_config()
    target = Path(cfg.model_path)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        local_dir=str(target),
        allow_patterns=list(MODEL_FILES),
    )
    missing = [f for f in MODEL_FILES if not (target / f).is_file()]
    if missing:
        print(f"bake incomplete, missing {missing} in {target}", file=sys.stderr)
        return 1
    digest = sha256_of(target / "model.bin")
    if digest != MODEL_SHA256:
        print(f"model.bin sha256 {digest} != expected {MODEL_SHA256}", file=sys.stderr)
        return 1

    problems = check_container_decode()
    if problems:
        print("container decode check failed: " + "; ".join(problems), file=sys.stderr)
        return 1

    result = FasterWhisperModel(cfg).transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), None)
    print(f"baked {MODEL_REPO}@{MODEL_REVISION} into {target}; loads with compute_type="
          f"{cfg.compute_type} (silence -> {result.text!r})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
