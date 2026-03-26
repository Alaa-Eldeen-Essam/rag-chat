import os
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
from typing import List, Optional
import logging

from langchain_community.document_loaders import TextLoader

from .BaseController import BaseController
from .ProjectController import ProjectController
from helpers.ocr import (
    ocr_image_file,
    extract_pdf_pages_with_ocr,
)
from models import ProcessingEnum

logger = logging.getLogger(__name__)

@dataclass
class Document:
    page_content: str
    metadata: dict
class ProcessController(BaseController):

    def __init__(self, project_id: str):
        super().__init__()

        self.project_id = project_id
        self.project_path = ProjectController().get_project_path(project_id=project_id)

    def get_file_extension(self, file_id: str):
        return os.path.splitext(file_id)[-1]

    def _resolve_file_path(self, file_id: str) -> str:
        return ProjectController().resolve_project_file_path(
            project_id=self.project_id,
            file_name=file_id,
        )

    def get_file_loader(self, file_id: str):

        file_ext = self.get_file_extension(file_id=file_id)
        try:
            file_path = self._resolve_file_path(file_id=file_id)
        except ValueError:
            logger.error("Invalid file path requested for loader: %s", file_id)
            return None

        if not os.path.exists(file_path):
            return None

        if file_ext == ProcessingEnum.TXT.value:
            return TextLoader(file_path, encoding="utf-8")

        if file_ext == ProcessingEnum.PDF.value:
            # PDF handling is custom and does not use a langchain loader here.
            return None

        return None

    def _extract_docx_text(self, file_path: str) -> Optional[str]:
        try:
            from docx import Document as DocxDocument
        except Exception as exc:
            logger.warning("python-docx not available for DOCX: %s", exc)
            return None

        try:
            doc = DocxDocument(file_path)
        except Exception as exc:
            logger.warning("Failed to open DOCX '%s': %s", file_path, exc)
            return None

        parts: List[str] = []
        for para in doc.paragraphs:
            text = (para.text or "").strip()
            if text:
                parts.append(text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    cell_text = (cell.text or "").strip()
                    if cell_text:
                        parts.append(cell_text)

        combined = "\n".join(parts).strip()
        return combined or None

    def _extract_doc_text(self, file_path: str) -> Optional[str]:
        tool = shutil.which("antiword") or shutil.which("catdoc")
        if not tool:
            logger.warning(
                "No DOC extractor found (antiword/catdoc). Install one to parse .doc files."
            )
            return None

        try:
            result = subprocess.run(
                [tool, file_path],
                capture_output=True,
                check=False,
            )
        except Exception as exc:
            logger.warning("Failed to run DOC extractor '%s': %s", tool, exc)
            return None

        output_bytes = result.stdout or b""
        if not output_bytes.strip():
            logger.warning("DOC extractor '%s' returned no text for '%s'", tool, file_path)
            return None

        decoded = None
        for encoding in ("utf-8", "cp1256", "windows-1256", "cp1252", "latin-1"):
            try:
                decoded = output_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            decoded = output_bytes.decode("utf-8", errors="replace")

        text = decoded.strip()
        if not text:
            logger.warning("DOC extractor '%s' returned no text for '%s'", tool, file_path)
            return None
        return text

    def _should_fallback_to_ocr(self, docs: Optional[list]) -> bool:
        """
        Decide if OCR should be used based on extracted text length and quality.
        """
        if not getattr(self.app_settings, "OCR_ENABLED", False):
            return False
        if not docs:
            return True

        total_text = "".join(
            getattr(rec, "page_content", "") or "" for rec in docs
        ).strip()

        # If we extracted almost nothing, let OCR try.
        if len(total_text) < 200:
            return True

        # Heuristic for "gibberish" text:
        # If only a small fraction of characters are readable letters/digits/whitespace
        # (e.g., encoded glyphs from PDFs), treat it as no usable text and fall back to OCR.
        # To keep it fast, only sample the first few thousand characters.
        sample = total_text[:4000]
        if not sample:
            return True

        readable_chars = 0
        for ch in sample:
            # Count letters, numbers, and whitespace from any script as "readable"
            if ch.isspace():
                readable_chars += 1
                continue
            cat = unicodedata.category(ch)
            if cat.startswith("L") or cat.startswith("N"):
                readable_chars += 1

        ratio = readable_chars / len(sample)

        # If less than ~50% of characters look readable, assume the text layer is garbage.
        if ratio < 0.5:
            return True

        return False

    def get_file_content(self, file_id: str, force_ocr: bool = False):
        """
        Load file content as a list of Document‑like objects.

        - TXT/PDF: use existing loaders first.
        - Images: use OCR directly.
        - PDFs with little/no text: fall back to page‑by‑page OCR when enabled.
        """
        file_ext = (self.get_file_extension(file_id=file_id) or "").lower()
        try:
            file_path = self._resolve_file_path(file_id=file_id)
        except ValueError:
            logger.error("Invalid file path requested for content extraction: %s", file_id)
            return None

        if not os.path.exists(file_path):
            return None

        # PDF handling with OCR detection
        if file_ext == ProcessingEnum.PDF.value:
            pages = extract_pdf_pages_with_ocr(
                path=file_path,
                lang=getattr(self.app_settings, "OCR_LANGS", "eng"),
                max_pages=getattr(self.app_settings, "OCR_MAX_PAGES", None),
                dpi=getattr(self.app_settings, "OCR_DPI", 300) or 300,
                force_ocr=force_ocr,
            )
            if not pages:
                return None

            docs: list[Document] = []
            for text, meta in pages:
                text = (text or "").strip()
                if not text:
                    continue
                docs.append(
                    Document(
                        page_content=text,
                        metadata=meta or {},
                    )
                )
            return docs

        if file_ext == ProcessingEnum.DOCX.value:
            text = self._extract_docx_text(file_path)
            if not text:
                return None
            return [
                Document(
                    page_content=text,
                    metadata={
                        "page_number": 1,
                        "file_type": "docx",
                    },
                )
            ]

        if file_ext == ProcessingEnum.DOC.value:
            text = self._extract_doc_text(file_path)
            if not text:
                return None
            return [
                Document(
                    page_content=text,
                    metadata={
                        "page_number": 1,
                        "file_type": "doc",
                    },
                )
            ]

        loader = self.get_file_loader(file_id=file_id)
        docs = loader.load() if loader else None

        # If OCR is disabled, keep existing behavior.
        if not getattr(self.app_settings, "OCR_ENABLED", False) and not force_ocr:
            # For images, there was no loader before, so we also keep behavior (no content).
            return docs

        # Always run OCR for images.
        image_exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif"}
        if file_ext in image_exts:
            text = ocr_image_file(file_path, lang=self.app_settings.OCR_LANGS)
            if not text.strip():
                return None
            return [
                Document(
                    page_content=text.strip(),
                    metadata={
                        "ocr_used": True,
                        "ocr_lang": self.app_settings.OCR_LANGS,
                    },
                )
            ]

        return docs

    def process_file_content(
        self,
        file_content: list,
        file_id: str,
        chunk_size: int = 500,
        overlap_size: int = 100,
    ):
        """
        Turn raw file pages into sentence-like segments first, then group them
        into chunks of approximately `chunk_size` characters with optional
        overlap. This makes it more likely that key facts (dates, places, names)
        stay together inside at least one chunk.
        """

        sentence_texts: List[str] = []
        sentence_metas: List[dict] = []

        for page_idx, rec in enumerate(file_content):
            text = getattr(rec, "page_content", "") or ""
            raw_meta = getattr(rec, "metadata", {}) or {}
            meta = dict(raw_meta)

            if "page_number" not in meta:
                page_from_meta = meta.get("page")
                try:
                    page_int = int(page_from_meta)
                except (TypeError, ValueError):
                    page_int = None
                meta["page_number"] = page_int if page_int is not None else page_idx + 1

            # Split into sentence-ish segments using punctuation and newlines.
            parts = re.split(r'(?<=[\.\!\؟\!؟])\s+|\n+', text)
            for s in parts:
                s = (s or "").strip()
                if len(s) > 1:
                    sentence_texts.append(s)
                    # Store a shallow copy so that later per‑sentence / per‑chunk
                    # adjustments to metadata (like page_number) do not alias
                    # across different sentences or pages.
                    sentence_metas.append(dict(meta))

        if not sentence_texts:
            return []

        chunks = self.process_simpler_splitter(
            texts=sentence_texts,
            metadatas=sentence_metas,
            chunk_size=chunk_size,
            overlap_size=overlap_size,
        )

        return chunks

    def process_simpler_splitter(
        self,
        texts: List[str],
        metadatas: List[dict],
        chunk_size: int,
        overlap_size: int = 0,
        splitter_tag: str = "\n",
    ):
        """
        Sentence-oriented splitter with character-based size and overlap,
        preserving basic metadata.

        For OCR‑derived content, this means `ocr_used` / `ocr_lang` flags will be
        propagated into the resulting chunks.
        """
        if not metadatas or len(metadatas) != len(texts):
            metadatas = [{} for _ in texts]

        chunks: List[Document] = []
        current_sentences: List[str] = []
        current_meta: dict = {}
        current_len = 0

        for text, meta in zip(texts, metadatas):
            s = (text or "").strip()
            if len(s) <= 1:
                continue

            meta = meta or {}

            # If we are aggregating sentences and suddenly see a sentence whose
            # page_number differs from the current chunk's page_number, flush
            # the current chunk first so that each chunk is associated with a
            # single logical page. This keeps page_number accurate for PDFs
            # (both text‑layer and OCR paths).
            if (
                current_sentences
                and current_meta
                and meta.get("page_number") is not None
                and current_meta.get("page_number") is not None
                and meta.get("page_number") != current_meta.get("page_number")
            ):
                chunk_text = splitter_tag.join(current_sentences).strip()
                if chunk_text:
                    chunks.append(
                        Document(
                            page_content=chunk_text,
                            metadata=current_meta or {},
                        )
                    )
                # Start a fresh chunk on the new page.
                current_sentences = []
                current_len = 0
                current_meta = {}

            if not current_sentences:
                current_meta = meta

            current_sentences.append(s)
            current_len += len(s) + len(splitter_tag)

            if current_len >= chunk_size:
                chunk_text = splitter_tag.join(current_sentences).strip()
                chunks.append(
                    Document(
                        page_content=chunk_text,
                        metadata=current_meta or {},
                    )
                )

                # Compute sentence-level overlap based on approximate character budget.
                if overlap_size > 0 and current_sentences:
                    overlap_sentences: List[str] = []
                    overlap_len = 0
                    for sentence in reversed(current_sentences):
                        if overlap_len >= overlap_size:
                            break
                        overlap_sentences.append(sentence)
                        overlap_len += len(sentence) + len(splitter_tag)
                    current_sentences = list(reversed(overlap_sentences))
                    current_len = overlap_len
                else:
                    current_sentences = []
                    current_len = 0

                current_meta = current_meta or {}

        if current_sentences:
            chunk_text = splitter_tag.join(current_sentences).strip()
            chunks.append(
                Document(
                    page_content=chunk_text,
                    metadata=current_meta or {},
                )
            )
        # Fallback: if any resulting chunk lacks an explicit page_number
        # (e.g., non‑PDF sources or legacy metadata), assign sequential
        # page numbers based on chunk order so that downstream consumers
        # can still display a sensible location reference.
        if chunks:
            for idx, doc in enumerate(chunks):
                meta = getattr(doc, "metadata", None) or {}
                if meta.get("page_number") is None:
                    meta["page_number"] = idx + 1
                doc.metadata = meta

        return chunks
    
