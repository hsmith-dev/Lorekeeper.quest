"""Text from a photo of session notes, read by the ml sidecar's /v1/ocr.

OCR (RapidOCR, PP-OCR ONNX models) runs in the `ml` sidecar, not in this
process: AD-1 forbids model packages in the web/worker image, and EasyOCR
(with its LGPL python-bidi dependency) left both images in E0-QA.9. The
sidecar applies the old in-process rule: the stripped non-empty lines,
joined with "\\n".

Failures are the client's typed errors (app/clients/errors.py):
ModelServiceUnavailable when the sidecar is down, loading past the timeout
or over its memory budget; ModelServiceError (status_code 422 / 413) when it
rejects the upload.
"""

from app.clients.ml import get_ml_client


async def extract_notes_from_image(image_bytes: bytes, filename: str = "image") -> str:
    return (await get_ml_client().ocr(image_bytes, filename)).strip()
