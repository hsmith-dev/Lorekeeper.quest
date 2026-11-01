# Lorekeeper `stt` sidecar: one process holding faster-whisper base for every
# backend worker (E0-Platform.5). Internal only: no published port, no nginx
# route (see docker-compose*.yml).
#
# Targets:
#   base  everything: CPU lock, baked weights, offline env, non-root user
#   gpu   local only, never published: adds the CUDA 12 cuBLAS / cuDNN 9
#         runtime wheels ctranslate2 needs on an NVIDIA GPU (NVIDIA EULA)
#   cpu   the default (last) stage, what compose and CI build
FROM python:3.11-slim AS base
WORKDIR /srv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STT_MODEL_PATH=/models/faster-whisper-base

# Audio is decoded by the ffmpeg CLI from Debian, run as a separate process
# (stt_service.models.decode_container). Its GPL-linked libraries are never
# loaded into the Python process: mere aggregation under the OS-package rule
# (docs/LICENSING.md, os_aggregate_allowlist in .github/license-policy.toml).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-nodeps.txt ./
# The lock: ctranslate2 (own CPU kernels), tokenizers, onnxruntime, hub. No av.
RUN pip install --no-cache-dir -r requirements.txt
# faster-whisper without its declared `av` dependency (PyAV bundles a
# GPL-linked FFmpeg; see requirements.txt). stt_service/whisper_loader.py
# imports it without av.
RUN pip install --no-cache-dir --no-deps -r requirements-nodeps.txt
# Guards, after the last pip install:
#  - no torch and no NVIDIA-proprietary nvidia-*/cuda-* wheels (unregistered);
#  - PyAV is absent: `import av` must fail in a fresh interpreter;
#  - the ffmpeg CLI is present.
RUN ! pip list --format=freeze | grep -iE '^(nvidia|cuda)[-_]|^torch==|^av==' \
    && ! python -c "import av" 2>/dev/null \
    && ffmpeg -hide_banner -version >/dev/null

COPY stt_service ./stt_service
COPY bake_models.py .
# faster_whisper imports here only through the av placeholder, and no real
# PyAV crept in with it.
RUN python -c "import sys; from stt_service.whisper_loader import whisper_model_class, PLACEHOLDER_ATTR; whisper_model_class(); sys.exit(not getattr(sys.modules['av'], PLACEHOLDER_ATTR, False))"
# Bake faster-whisper-base at the pinned revision (sha256-verified) and load it
# once, so a broken bake fails the build rather than the first request.
RUN python bake_models.py

# Weights are in the image; never reach for the network at runtime.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd -m sttuser && chown -R sttuser /srv
USER sttuser

EXPOSE 8000

# /healthz only checks the baked model.bin (the model itself loads lazily on
# the first request), so the container turns healthy quickly.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

# One worker on purpose: the whole point is one copy of the model.
CMD ["uvicorn", "stt_service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]


# Local-only GPU build (docker build --target gpu). Never published: the
# NVIDIA wheels are proprietary and unregistered (E0-Platform.7 owns GPU
# compose). Versions are what `nvidia-cudnn-cu12>=9,<10` + `nvidia-cublas-cu12`
# resolve to for Python 3.11 on x86_64.
FROM base AS gpu
USER root
RUN pip install --no-cache-dir nvidia-cublas-cu12==12.9.3.13 nvidia-cudnn-cu12==9.27.0.42
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib \
    STT_DEVICE=cuda
USER sttuser


# Default target: the CPU image, identical to `base`.
FROM base AS cpu
