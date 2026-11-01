---
title: 'E0-QA.9 (OCR half) RapidOCR replaces EasyOCR, removing python-bidi (LGPL-3.0)'
type: 'chore'
created: '2026-11-01'
status: 'done'
baseline_revision: '61abdbaea6e82be7c59c94e35d739c6d27c10d0d'
---

## Intent

Owner decision 2026-11-01 (OD-3): replace rather than accept the python-bidi
licence exception. python-bidi came only through easyocr, so EasyOCR leaves
both images and OCR becomes RapidOCR (Apache-2.0) on onnxruntime (MIT) with
PaddleOCR PP-OCRv6 small models (Apache-2.0) in the `ml` sidecar.

## Boundaries

- Backend: in-process model packages are forbidden (AD-1, the import-linter
  `models` contract and `model_packages_baseline.txt` only shrink), so
  `vision_service` calls the sidecar's existing `/v1/ocr` through
  `app.clients.ml` rather than loading RapidOCR in the web process. Nothing
  else moves (the rest of E0-Platform.6 stays open).
- Not touched: compose files and the redis row (Valkey sibling), fpdf2 /
  export_service / PDF rows (E0-QA.9a), sprint-status, epics.

## Changes

- `ml` sidecar: `RapidOcrReader` (EXIF-aware, same stripped-lines rule),
  config `OCR_MODELS` (det / cls / rec .onnx URLs + sha256),
  `/models/rapidocr`, bake downloads + verifies each file and requires the
  rendered check text to read back exactly; torchvision and easyocr out of
  the Dockerfile and the lock (lock regenerated: +rapidocr, onnxruntime,
  omegaconf, colorlog, flatbuffers, protobuf, six; -easyocr, python-bidi,
  torchvision, scikit-image, imageio, tifffile, lazy-loader, ninja).
  `ML_OCR_COST_MB` default 900 -> 400 (measured +230 MB resident).
- Backend: `vision_service` -> `get_ml_client().ocr()`; ingest route maps
  ModelServiceUnavailable -> 503, sidecar 413 -> 413, 422 -> "could not
  extract text". easyocr removed from requirements, `.importlinter`
  ratchet, baseline and frozen ceilings.
- Licences: python-bidi `[[exception]]` and register rows for easyocr,
  python-bidi, its EasyOCR-only deps and the two EasyOCR model zips removed;
  three `rapidocr-*` model rows (sha256) and six python rows added; images
  narrowed where packages left the backend. `docs/LICENSING.md` records the
  decision. A test now asserts python-bidi fails in both editions.

## Verification (desktop, 2026-11-01)

Synthetic set: 3 printed, 3 phone-photo-like, 48 handwriting (8 Google
handwriting fonts x 3 texts x clean/photo); no sample images exist in the repo.
Inside the built ml images, offline (`--network none`), `--cpus 4`:

| | printed CER | photo CER | handwriting CER | handwriting WER* | mean latency | OCR RSS delta |
|---|---|---|---|---|---|---|
| EasyOCR (main) | 0.015 | 0.032 | 0.108 | 0.290 | 2.4 s | +327 MB |
| RapidOCR PP-OCRv6 small | 0.000 | 0.000 | 0.011 | 0.021 | 3.3 s | +230 MB |

*punctuation-insensitive. Also benchmarked (standalone): PP-OCRv4 mobile en
(hand CER 0.071), PP-OCRv5 mobile (0.040), PP-OCRv6 tiny (0.029, ~1.6 s).
Image: 4.63 GB -> 4.57 GB; weights 94 MB -> 31 MB. Licence scan of the new
ml image: 0 violations in both editions, no python-bidi. Backend suite 753
passed / 21 skipped; ml suite in the real image 57 passed.

## Auto Run Result

Done. Needs desktop verification: real phone photos of handwritten notes
(none in repo): `docker compose up ml backend` then POST a photo to
`/api/ingest/image`; latency is ~40% slower than EasyOCR per image on 4 CPUs
(PP-OCRv6 tiny is the fallback if that matters).
