FROM python:3.11-slim
WORKDIR /app
# WeasyPrint's system libraries and fonts for the campaign PDF export (E0-QA.9);
# fonts-dejavu-extra has the oblique faces (WeasyPrint does not synthesise italics)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fontconfig fonts-dejavu-core fonts-dejavu-extra \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# No model packages (E0-Platform.6): embeddings, NER and OCR come from the ml
# sidecar, speech from stt. Every requirement has a binary wheel on amd64 and
# arm64, so no compiler is needed. CI-3 (scripts/check_model_packages.py)
# fails if torch, spaCy or another model package comes back.
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
