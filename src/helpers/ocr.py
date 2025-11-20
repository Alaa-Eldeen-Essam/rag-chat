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


def _clean_utf8_text(text: str) -> str:
    """
    Normalize text to UTF-8 by removing characters that cannot be encoded.
    """
    return (text or "").encode("utf-8", errors="ignore").decode("utf-8", errors="ignore").strip()


def requires_ocr_for_pdf(path: str) -> bool:
    """
    Inspect a PDF to decide whether OCR is required.

    Returns True when:
      - The PDF contains no extractable text.
      - Any span contains invalid / non-UTF-8 encodings (e.g., replacement chars).
    Returns False only when text exists and appears valid.
    """
    try:
        doc = fitz.open(path)
    except Exception as exc:
        logger.error("Failed to open PDF '%s' to check OCR need: %s", path, exc)
        return True

    has_text = False
    bad_encoding = False

    try:
        for page in doc:
            page_txt = page.get_text() or ""
            if page_txt.strip():
                has_text = True

            # Inspect spans for encoding quality
            try:
                raw = page.get_text("rawdict") or {}
                blocks = raw.get("blocks", [])
                for block in blocks:
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            txt = span.get("text", "")
                            if not txt:
                                continue
                            # Replacement characters or encode errors -> bad
                            if "\ufffd" in txt:
                                bad_encoding = True
                                break
                            try:
                                txt.encode("utf-8")
                            except UnicodeEncodeError:
                                bad_encoding = True
                                break
                        if bad_encoding:
                            break
                    if bad_encoding:
                        break
                if bad_encoding:
                    break
            except Exception:
                # If we cannot inspect spans reliably, fall back to OCR.
                bad_encoding = True
                break
    finally:
        doc.close()

    if not has_text:
        return True
    if bad_encoding:
        return True
    return False


def ocr_pdf_to_text(path: str, lang: str, max_pages: Optional[int] = None, dpi: int = 300) -> str:
    """
    OCR an entire PDF and return the concatenated UTF-8 text.
    """
    ocr_results = ocr_pdf_file(path=path, lang=lang, max_pages=max_pages, dpi=dpi)
    combined = "\n\n".join(text for text, _meta in ocr_results if text)
    return _clean_utf8_text(combined)


def extract_pdf_text_with_ocr(path: str, lang: str, max_pages: Optional[int] = None, dpi: int = 300) -> Tuple[str, bool]:
    """
    Extract PDF text using PyMuPDF, falling back to OCR when needed.

    Returns (text, used_ocr).
    """
    needs_ocr = requires_ocr_for_pdf(path)
    if not needs_ocr:
        try:
            doc = fitz.open(path)
        except Exception as exc:
            logger.error("Failed to open PDF '%s' for text extraction: %s", path, exc)
            needs_ocr = True
        else:
            try:
                parts: List[str] = []
                for page in doc:
                    parts.append(page.get_text() or "")
                text = _clean_utf8_text("\n\n".join(parts))
                if text:
                    return text, False
                needs_ocr = True
            finally:
                doc.close()

    # OCR path
    text = ocr_pdf_to_text(path=path, lang=lang, max_pages=max_pages, dpi=dpi)
    return text, True
