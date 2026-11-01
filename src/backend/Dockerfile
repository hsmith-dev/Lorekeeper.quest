FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
# CPU-only torch/torchvision first (E0-Platform.2): a plain PyPI resolve on
# x86-64 pulls CUDA torch and ~15 NVIDIA-proprietary nvidia-*/cuda-* wheels.
# The CPU index has +cpu wheels for amd64 and arm64 alike. Pins match
# licenses/register.yaml; the requirements install then uses the same CPU
# extra index as CI's licence job.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch==2.15.0+cpu torchvision==0.29.2+cpu
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt
RUN python -m spacy download en_core_web_trf
# Fail the build if any earlier layer re-resolved torch to CUDA or added NVIDIA wheels
RUN python -c "import torch, sys; sys.exit(torch.version.cuda is not None or torch.cuda.is_available())" \
    && ! pip list --format=freeze | grep -iE '^(nvidia|cuda)[-_]'
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
