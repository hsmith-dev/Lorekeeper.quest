# Lorekeeper `ml` sidecar: one process holding MiniLM embeddings and spaCy
# en_core_web_trf NER for every backend worker (E0-Platform.3). Internal
# only: no published port, no nginx route (see docker-compose*.yml).
FROM python:3.11-slim
WORKDIR /srv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ML_EMBED_MODEL_PATH=/models/all-MiniLM-L6-v2

# The CUDA/NVIDIA guard (E0-Platform.2) runs after every install layer: a
# plain PyPI resolve on x86-64 pulls CUDA torch and ~15 NVIDIA-proprietary
# nvidia-*/cuda-* wheels, which licenses/register.yaml deliberately omits.
COPY requirements.txt .
# CPU-only torch first, from the PyTorch CPU index (+cpu wheels for amd64 and
# arm64). Pin matches requirements.txt and licenses/register.yaml.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch==2.15.0+cpu
RUN python -c "import torch, sys; sys.exit(torch.version.cuda is not None or torch.cuda.is_available())" \
    && ! pip list --format=freeze | grep -iE '^(nvidia|cuda)[-_]'
# Full lock (includes the en_core_web_trf 3.8.0 wheel, hash-pinned).
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt
RUN python -c "import torch, sys; sys.exit(torch.version.cuda is not None or torch.cuda.is_available())" \
    && ! pip list --format=freeze | grep -iE '^(nvidia|cuda)[-_]'

COPY ml_service ./ml_service
COPY bake_models.py .
# Bake MiniLM at the pinned revision (sha256-verified) and load both models
# once, so a broken bake fails the build rather than the first request.
RUN python bake_models.py

# Weights are in the image; never reach for the network at runtime.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd -m mluser && chown -R mluser /srv
USER mluser

EXPOSE 8000

# Models load before uvicorn accepts connections; en_core_web_trf on a cold
# CPU can take a minute, hence the long start period.
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]

# One worker on purpose: the whole point is one copy of each model.
CMD ["uvicorn", "ml_service.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
