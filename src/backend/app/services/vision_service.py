import asyncio
import io
import logging
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

logger = logging.getLogger(__name__)

_reader = None
_executor = ThreadPoolExecutor(max_workers=1)


def _load_reader() -> None:
    global _reader
    if _reader is not None:
        return
    import easyocr
    logger.info("Loading EasyOCR text recognition model...")
    _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    logger.info("EasyOCR loaded.")


def _run_extraction(image_bytes: bytes) -> str:
    _load_reader()
    import numpy as np
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_array = np.array(image)
    results = _reader.readtext(img_array, detail=0, paragraph=True)
    return "\n".join(line.strip() for line in results if line.strip())


async def extract_notes_from_image(image_bytes: bytes) -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_extraction, image_bytes)
