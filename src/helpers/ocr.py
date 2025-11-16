import io
import logging
from typing import Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


def ocr_image_file(path: str, lang: str) -> str:
    """
    Run Tesseract OCR on a single image file.

    Returns the extracted text (may be empty on failure).
    """
    try:
        with Image.open(path) as img:
            # Convert to RGB to avoid mode issues
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            text = pytesseract.image_to_string(img, lang=lang or "eng")
            return text or ""
    except Exception as exc:
        logger.error("OCR failed for image '%s': %s", path, exc)
        return ""


def ocr_pdf_file(
    path: str,
    lang: str,
    max_pages: Optional[int] = None,
    dpi: int = 300,
) -> List[Tuple[str, Dict]]:
    """
    Run Tesseract OCR page‑by‑page on a PDF using PyMuPDF rendering.

    Returns a list of (text, metadata) tuples, where metadata at least contains:
      - page: 1‑based page index
      - ocr_used: True
      - ocr_lang: language string passed to Tesseract
    """
    results: List[Tuple[str, Dict]] = []

    try:
        doc = fitz.open(path)
    except Exception as exc:
        logger.error("Failed to open PDF for OCR '%s': %s", path, exc)
        return results

    try:
        page_count = doc.page_count
        last_page = page_count if max_pages is None else min(page_count, max_pages)

        for page_index in range(0, last_page):
            try:
                page = doc.load_page(page_index)
                pix = page.get_pixmap(dpi=dpi)
                mode = "RGBA" if pix.alpha else "RGB"
                img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")

                text = pytesseract.image_to_string(img, lang=lang or "eng")
                text = (text or "").strip()
                if not text:
                    continue

                metadata = {
                    "page": page_index + 1,
                    "ocr_used": True,
                    "ocr_lang": lang or "eng",
                }
                results.append((text, metadata))
            except Exception as exc_page:
                logger.error(
                    "OCR failed for page %s of '%s': %s",
                    page_index + 1,
                    path,
                    exc_page,
                )
                continue
    finally:
        doc.close()

    return results

