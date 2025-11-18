import os
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

from langchain_community.document_loaders import PyMuPDFLoader, TextLoader

from .BaseController import BaseController
from .ProjectController import ProjectController
from helpers.ocr import ocr_image_file, ocr_pdf_file
from models import ProcessingEnum

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

    def get_file_loader(self, file_id: str):

        file_ext = self.get_file_extension(file_id=file_id)
        file_path = os.path.join(self.project_path, file_id)

        if not os.path.exists(file_path):
            return None

        if file_ext == ProcessingEnum.TXT.value:
            return TextLoader(file_path, encoding="utf-8")

        if file_ext == ProcessingEnum.PDF.value:
            return PyMuPDFLoader(file_path)

        return None

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

    def get_file_content(self, file_id: str):
        """
        Load file content as a list of Document‑like objects.

        - TXT/PDF: use existing loaders first.
        - Images: use OCR directly.
        - PDFs with little/no text: fall back to page‑by‑page OCR when enabled.
        """
        file_ext = (self.get_file_extension(file_id=file_id) or "").lower()
        file_path = os.path.join(self.project_path, file_id)

        if not os.path.exists(file_path):
            return None

        loader = self.get_file_loader(file_id=file_id)
        docs = loader.load() if loader else None

        # If OCR is disabled, keep existing behavior.
        if not getattr(self.app_settings, "OCR_ENABLED", False):
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

        # For PDFs: try normal extraction, then fall back to OCR if needed.
        if file_ext == ProcessingEnum.PDF.value:
            if not self._should_fallback_to_ocr(docs):
                return docs

            ocr_results = ocr_pdf_file(
                path=file_path,
                lang=self.app_settings.OCR_LANGS,
                max_pages=self.app_settings.OCR_MAX_PAGES,
                dpi=self.app_settings.OCR_DPI or 300,
            )
            if not ocr_results:
                # If OCR fails or returns nothing, keep whatever we had.
                return docs

            ocr_docs = [
                Document(
                    page_content=text,
                    metadata=metadata,
                )
                for (text, metadata) in ocr_results
            ]
            return ocr_docs

        return docs

    def process_file_content(
        self,
        file_content: list,
        file_id: str,
        chunk_size: int = 900,
        overlap_size: int = 300,
    ):
        """
        Turn raw file pages into sentence-like segments first, then group them
        into chunks of approximately `chunk_size` characters with optional
        overlap. This makes it more likely that key facts (dates, places, names)
        stay together inside at least one chunk.
        """

        sentence_texts: List[str] = []
        sentence_metas: List[dict] = []

        for rec in file_content:
            text = getattr(rec, "page_content", "") or ""
            meta = getattr(rec, "metadata", {}) or {}

            # Split into sentence-ish segments using punctuation and newlines.
            parts = re.split(r'(?<=[\.\!\؟\!؟])\s+|\n+', text)
            for s in parts:
                s = (s or "").strip()
                if len(s) > 1:
                    sentence_texts.append(s)
                    sentence_metas.append(meta)

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

            if not current_sentences:
                current_meta = meta or {}

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

        return chunks
    
