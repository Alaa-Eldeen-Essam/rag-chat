from dataclasses import dataclass
import os
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
        Decide if OCR should be used based on extracted text length.
        """
        if not getattr(self.app_settings, "OCR_ENABLED", False):
            return False
        if not docs:
            return True

        total_text = "".join(
            getattr(rec, "page_content", "") or "" for rec in docs
        ).strip()
        # If we extracted almost nothing, let OCR try.
        return len(total_text) < 200

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

    def process_file_content(self, file_content: list, file_id: str,
                            chunk_size: int=1200, overlap_size: int=250):

        file_content_texts = [
            rec.page_content
            for rec in file_content
        ]

        file_content_metadata = [
            rec.metadata
            for rec in file_content
        ]

        # chunks = text_splitter.create_documents(
        #     file_content_texts,
        #     metadatas=file_content_metadata
        # )

        chunks = self.process_simpler_splitter(
            texts=file_content_texts,
            metadatas=file_content_metadata,
            chunk_size=chunk_size,
        )

        return chunks

    def process_simpler_splitter(
        self,
        texts: List[str],
        metadatas: List[dict],
        chunk_size: int,
        splitter_tag: str = "\n",
    ):
        """
        Simple character‑based splitter that now preserves basic metadata.

        For OCR‑derived content, this means `ocr_used` / `ocr_lang` flags will be
        propagated into the resulting chunks.
        """
        if not metadatas or len(metadatas) != len(texts):
            metadatas = [{} for _ in texts]

        chunks: List[Document] = []
        current_chunk = ""
        current_meta: dict = {}

        for text, meta in zip(texts, metadatas):
            # split by splitter_tag
            lines = [
                doc.strip()
                for doc in (text or "").split(splitter_tag)
                if len(doc.strip()) > 1
            ]

            for line in lines:
                if not current_chunk:
                    current_meta = meta or {}

                current_chunk += line + splitter_tag
                if len(current_chunk) >= chunk_size:
                    chunks.append(
                        Document(
                            page_content=current_chunk.strip(),
                            metadata=current_meta or {},
                        )
                    )
                    current_chunk = ""
                    current_meta = {}

        if current_chunk:
            chunks.append(
                Document(
                    page_content=current_chunk.strip(),
                    metadata=current_meta or {},
                )
            )

        return chunks
    
