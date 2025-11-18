import json
import logging
import re
from typing import Any, Dict, List, Optional

from .BaseController import BaseController
from models.db_schemes import DataChunk, Project
from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)

# Basic Arabic month names for simple date extraction.
AR_MONTHS_PATTERN = (
    "يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|"
    "أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر"
)

# Basic English month names for simple date extraction.
EN_MONTHS_PATTERN = (
    "January|February|March|April|May|June|July|August|September|October|November|December|"
    "Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)

# Match patterns like:
# - "2 ديسمبر 2021"
# - "2\nديسمبر2021"
# - "December 2, 2021"
# - "2 December 2021"
DATE_REGEX = re.compile(
    rf"("
    rf"\d{{1,2}}\D{{0,7}}(?:{AR_MONTHS_PATTERN}|{EN_MONTHS_PATTERN})\D{{0,7}}\d{{4}}"
    rf"|"
    rf"(?:{AR_MONTHS_PATTERN}|{EN_MONTHS_PATTERN})\D{{0,7}}\d{{4}}"
    rf")"
)

# Maximum number of evidence chunks to send to the LLM for a single answer.
EVIDENCE_DOC_LIMIT = 5

# Approximate character budget for all evidence text passed to the LLM for
# a single answer. This helps keep prompts focused and reduces hallucination
# risk on very long documents.
EVIDENCE_CHAR_BUDGET = 4000

class NLPController(BaseController):

    def __init__(self, vectordb_client, generation_client, 
                 embedding_client, template_parser):
        super().__init__()

        self.vectordb_client = vectordb_client
        self.generation_client = generation_client
        self.embedding_client = embedding_client
        self.template_parser = template_parser

    def create_collection_name(self, project_id: str):
        return f"collection_{self.vectordb_client.default_vector_size}_{project_id}".strip()
    
    async def reset_vector_db_collection(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        return await self.vectordb_client.delete_collection(collection_name=collection_name)
    
    async def get_vector_db_collection_info(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        collection_info = await self.vectordb_client.get_collection_info(collection_name=collection_name)

        return json.loads(
            json.dumps(collection_info, default=lambda x: x.__dict__)
        )

    def _coerce_metadata_dict(self, metadata: Optional[Any]) -> Optional[Dict[str, Any]]:
        if isinstance(metadata, dict):
            return metadata
        if metadata is None:
            return None

        if hasattr(metadata, "dict"):
            try:
                meta_dict = metadata.dict()  # type: ignore[call-arg]
                if isinstance(meta_dict, dict):
                    return meta_dict
            except Exception:
                pass

        if hasattr(metadata, "__dict__"):
            meta_dict = getattr(metadata, "__dict__", None)
            if isinstance(meta_dict, dict):
                return meta_dict

        return None

    def _detect_question_type(self, query: str) -> str:
        """
        Very lightweight question type detector for Arabic and English.
        Returns one of: 'when', 'why', 'where', 'who', 'how_many', or ''.
        """
        if not query:
            return ""

        q = (query or "").strip().lower()

        # Basic Arabic / English "when" markers.
        if "متى" in q or q.startswith("when "):
            return "when"

        # Basic Arabic / English "why" markers, including common rephrasings.
        if (
            "لماذا" in q
            or "لماذا لم" in q
            or q.startswith("why ")
            or "ما سبب" in q
            or "ما هو سبب" in q
            or "ما هي أسباب" in q
            or "ما الاسباب" in q
            or "ما الأسباب" in q
            or "ما الذي دفع" in q
            or "what is the reason" in q
            or "what's the reason" in q
            or "what is the cause" in q
            or "what caused" in q
        ):
            return "why"

        # Basic "where" markers.
        if "أين" in q or q.startswith("where "):
            return "where"

        # Basic "who" markers.
        if "من " in q or q.startswith("who "):
            return "who"

        # Basic "how many" markers (numeric questions).
        if "كم " in q or "how many" in q:
            return "how_many"

        return ""

    def _normalize_label_value(self, value: str) -> str:
        label = (value or "").strip()
        if not label:
            return ""
        normalized = label.replace("\\", "/")
        if "/" in normalized:
            normalized = normalized.split("/")[-1]
        return normalized

    def _resolve_document_label(
        self,
        metadata: Optional[Any],
        fallback_label: str,
        asset_labels: Optional[Dict[int, str]] = None,
        asset_labels_by_name: Optional[Dict[str, str]] = None,
        asset_id_hint: Optional[int] = None,
    ) -> str:
        metadata_dict = self._coerce_metadata_dict(metadata)

        candidate_asset_id = asset_id_hint
        if candidate_asset_id is None and metadata_dict:
            candidate_asset_id = metadata_dict.get("asset_id")

        if asset_labels and candidate_asset_id is not None:
            try:
                label = asset_labels.get(int(candidate_asset_id))
            except (ValueError, TypeError):
                label = None
            if label:
                return self._normalize_label_value(label)

        if metadata_dict:
            for key in ("source_name", "original_filename", "original_name", "filename", "name", "source"):
                value = metadata_dict.get(key)
                if isinstance(value, str):
                    cleaned = self._normalize_label_value(value)
                    if cleaned:
                        if asset_labels_by_name and cleaned in asset_labels_by_name:
                            return asset_labels_by_name[cleaned]
                        return cleaned

        return self._normalize_label_value(fallback_label)
    
    async def index_into_vector_db(self, project: Project, chunks: List[DataChunk],
                                   chunks_ids: List[int], 
                                   do_reset: bool = False):
        
        # step1: get collection name
        collection_name = self.create_collection_name(project_id=project.project_id)

        # step2: manage items
        texts = [c.chunk_text for c in chunks]
        metadata = [c.chunk_metadata for c in chunks]
        vectors = self.embedding_client.embed_text(
            text=texts,
            document_type=DocumentTypeEnum.DOCUMENT.value,
        )

        if not vectors or len(vectors) != len(texts):
            logger.error("Embedding client returned invalid vectors for indexing")
            return False

        # step3: create collection if not exists
        _ = await self.vectordb_client.create_collection(
            collection_name=collection_name,
            embedding_size=self.embedding_client.embedding_size,
            do_reset=do_reset,
        )

        # step4: insert into vector db
        _ = await self.vectordb_client.insert_many(
            collection_name=collection_name,
            texts=texts,
            metadata=metadata,
            vectors=vectors,
            record_ids=chunks_ids,
        )

        return True

    async def search_vector_db_collection(
        self,
        project: Project,
        text: str,
        limit: int = 10,
        doc_types: Optional[List[str]] = None,
        asset_ids: Optional[List[int]] = None,
        keywords: Optional[List[str]] = None,
    ):

        # step1: get collection name
        query_vector = None
        collection_name = self.create_collection_name(project_id=project.project_id)

        # step2: get text embedding vector
        vectors = self.embedding_client.embed_text(text=text, 
                                                 document_type=DocumentTypeEnum.QUERY.value)

        if not vectors or len(vectors) == 0:
            return False
        
        if isinstance(vectors, list) and len(vectors) > 0:
            query_vector = vectors[0]

        if not query_vector:
            return False  

        # step3: do semantic search
        results = await self.vectordb_client.search_by_vector(
            collection_name=collection_name,
            vector=query_vector,
            limit=limit
        )

        if not results:
            return False

        if doc_types:
            doc_types_normalized = {dt.lower() for dt in doc_types}
            filtered_results = []
            for result in results:
                metadata = getattr(result, "metadata", None)
                chunk_type = None
                if isinstance(metadata, dict):
                    chunk_type = metadata.get("doc_type", metadata.get("document_type"))
                elif metadata is not None and hasattr(metadata, "get"):
                    chunk_type = metadata.get("doc_type")

                if chunk_type and chunk_type.lower() in doc_types_normalized:
                    filtered_results.append(result)

            if filtered_results:
                results = filtered_results
            else:
                return []

        if asset_ids:
            asset_id_set = {int(asset_id) for asset_id in asset_ids if asset_id is not None}
            filtered_results = []
            for result in results:
                metadata = getattr(result, "metadata", None)
                metadata_asset_id = None
                if isinstance(metadata, dict):
                    metadata_asset_id = metadata.get("asset_id")
                elif metadata is not None and hasattr(metadata, "get"):
                    metadata_asset_id = metadata.get("asset_id")

                if metadata_asset_id is not None:
                    try:
                        if int(metadata_asset_id) in asset_id_set:
                            filtered_results.append(result)
                    except (ValueError, TypeError):
                        continue

            if filtered_results:
                results = filtered_results
            else:
                return []

        # Optional keyword / lexical filtering: keep hits that contain at least
        # one of the query keywords, if provided.
        if keywords:
            normalized_keywords = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
            if normalized_keywords:
                filtered_results = []
                for result in results:
                    text_value = getattr(result, "text", "") or ""
                    t_lower = text_value.lower()
                    if any(kw in t_lower for kw in normalized_keywords):
                        filtered_results.append(result)

                if filtered_results:
                    results = filtered_results

        return results

    def _try_extract_direct_answer(self, query: str, documents: List[Any], question_type: str) -> Optional[str]:
        """
        Lightweight, retrieval-side extraction of very simple factual answers
        (dates, simple purposes) from the retrieved documents before passing
        everything to the LLM. Intended to be language-agnostic for Arabic
        and English where possible.
        """
        if not query or not documents or not question_type:
            return None

        corpus = "\n".join(
            (getattr(doc, "text", "") or "") for doc in documents
        )
        if not corpus:
            return None

        if question_type == "when":
            match = DATE_REGEX.search(corpus)
            if match:
                candidate = match.group(1).strip()
                if candidate:
                    return candidate
            return None

        if question_type == "why":
            # Split corpus into coarse sentences.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)

            def normalize_arabic(text: str) -> str:
                """Light normalization to make OCR variants more robust."""
                # Strip diacritics and tatweel
                text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
                # Normalize common alef forms and taa marbuta / ya
                text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                text = text.replace("ى", "ي").replace("ة", "ه")
                # Collapse whitespace
                text = re.sub(r"\s+", " ", text)
                return text

            # Travel-related verbs / phrases (normalized Arabic + English).
            travel_keywords = [
                "سافر", "ذهب", "توجه", "زار", "رحل",  # Arabic verbs
                "سفر", "زيارة",
                "traveled", "travelled", "went", "visited", "journeyed",
            ]

            # Purpose pattern: "ل" + 2–8 Arabic letters, then a meeting-like noun.
            purpose_pattern = re.compile(
                r"(ل[اأإآبتثجحخدذرزسشصضطظعغفقكلمنهوي]{2,8}\s*"
                r"(?:اجتماع|اجتماعا|مؤتمر|قمة|لقاء|meeting|summit|conference))",
                flags=re.IGNORECASE,
            )

            # Basic purpose triggers as a fallback matcher (more general).
            triggers = [
                # Arabic purpose / cause markers (normalized)
                "لحضور", "لحض", "للمشاركة", "لتقديم", "للتفاوض", "لعقد",
                "من اجل", "بهدف", "لان", "لأن", "بسبب", "نتيجه", "نتيجة",
                # English purpose / cause markers
                "to attend", "in order to", "for the purpose of",
                "because", "because of", "due to", "as a result of",
            ]

            lowered_query = (query or "").lower()
            normalized_query = normalize_arabic(lowered_query)

            # Ignore generic question words.
            stop_tokens = {"لماذا", "why", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", normalized_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            # First pass: pattern-based extraction bound to travel + query context.
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue

                low = s.lower()
                norm = normalize_arabic(low)

                # Require at least one travel-related keyword.
                if not any(tv in norm for tv in travel_keywords):
                    continue

                # Prefer sentences that share some tokens with the query.
                if query_tokens and not any(tok in norm for tok in query_tokens):
                    continue

                # Look for an explicit "ل + noun/verb" purpose fragment.
                m = purpose_pattern.search(low)
                if m:
                    start = m.start()
                    # Extract until the next major punctuation mark.
                    tail = s[start:]
                    p = re.search(r"[\.!\?؟]", tail)
                    end = start + p.start() if p else len(s)
                    reason_fragment = s[start:end].strip()
                    if reason_fragment:
                        return reason_fragment

            # Fallback: trigger-based sentence scoring (legacy behavior, but
            # using normalized text for robustness).
            best_sentence = None
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                norm = normalize_arabic(low)
                if any(trigger in norm for trigger in triggers):
                    # Prefer sentences that share some tokens with the query.
                    if query_tokens and any(tok in norm for tok in query_tokens):
                        best_sentence = s
                        break
                    if best_sentence is None:
                        best_sentence = s

            if best_sentence:
                return best_sentence.strip()

        if question_type == "where":
            # Very lightweight extraction of a location-bearing sentence with
            # simple scoring instead of first match, to reduce misfires.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)

            def normalize_arabic(text: str) -> str:
                text = re.sub(r"[ًٌٍَُِّْـ]", "", text)
                text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                text = text.replace("ى", "ي").replace("ة", "ه")
                text = re.sub(r"\s+", " ", text)
                return text

            lowered_query = (query or "").lower()
            norm_query = normalize_arabic(lowered_query)
            stop_tokens = {"اين", "أين", "where", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", norm_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            location_markers = ["في ", "في-", "الى ", "إلى ", "near", " in ", " at ", " to "]

            best_sentence = None
            best_score = 0
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                norm = normalize_arabic(low)

                score = 0
                if any(marker in norm for marker in location_markers):
                    score += 1

                overlap = 0
                for tok in query_tokens:
                    if tok in norm:
                        overlap += 1
                score += overlap

                if score > best_score:
                    best_score = score
                    best_sentence = s

            if best_sentence and best_score > 0:
                return best_sentence.strip()

        if question_type == "how_many":
            # Simple numeric extraction: look for a sentence with a number and
            # some overlap with the query, preferring higher overlap.
            sentences = re.split(r"[\.!\?؟\n]+", corpus)
            lowered_query = (query or "").lower()
            stop_tokens = {"كم", "how", "many", "?", "؟"}
            query_tokens = [
                tok
                for tok in re.findall(r"\w+", lowered_query, flags=re.UNICODE)
                if tok not in stop_tokens and len(tok) > 2
            ]

            numeric_pattern = re.compile(r"\d+")

            best_sentence = None
            best_score = 0
            for sent in sentences:
                s = sent.strip()
                if not s:
                    continue
                low = s.lower()
                if not numeric_pattern.search(low):
                    continue

                overlap = 0
                for tok in query_tokens:
                    if tok in low:
                        overlap += 1

                if overlap > best_score:
                    best_score = overlap
                    best_sentence = s

            if best_sentence and best_score > 0:
                return best_sentence.strip()

        # Other types could be added here (where, who) as needed.
        return None

    async def answer_rag_question(self, project: Project, query: str, limit: int = 10,
                            chat_messages: Optional[List[Dict[str, str]]] = None,
                            stream: bool = False, collector: Optional[dict] = None,
                            doc_types: Optional[List[str]] = None,
                            asset_ids: Optional[List[int]] = None,
                            asset_labels: Optional[Dict[int, str]] = None,
                            asset_labels_by_name: Optional[Dict[str, str]] = None):

        question_type = self._detect_question_type(query)

        # Build an augmented retrieval query that incorporates recent
        # conversation turns (if any) so that follow-up questions using
        # pronouns like "هناك / there" still retrieve the right chunks.
        retrieval_text = query or ""
        if chat_messages:
            parts: List[str] = []
            for msg in chat_messages[-3:]:
                prompt_part = (msg.get("prompt") or "").strip()
                answer_part = (msg.get("answer") or "").strip()
                if prompt_part:
                    parts.append(prompt_part)
                if answer_part:
                    parts.append(answer_part)
            if parts:
                retrieval_text = "\n".join(parts + [query or ""])
        
        # step1: retrieve related documents
        retrieved_documents = await self.search_vector_db_collection(
            project=project,
            text=retrieval_text,
            limit=limit,
            doc_types=doc_types,
            asset_ids=asset_ids,
        )

        direct_hint = self._try_extract_direct_answer(
            query=query,
            documents=retrieved_documents or [],
            question_type=question_type,
        )

        # Try to resolve a human-readable label for the document that most
        # likely contains the direct hint (e.g., original filename), so that
        # we can say "according to <document>" instead of "according to the
        # documents" in deterministic answers.
        doc_label_for_hint: Optional[str] = None
        if direct_hint and retrieved_documents:
            chosen_doc = None
            for doc in retrieved_documents:
                text_value = getattr(doc, "text", "") or ""
                if direct_hint in text_value:
                    chosen_doc = doc
                    break
            if chosen_doc is None:
                chosen_doc = retrieved_documents[0]

            try:
                doc_label_for_hint = self._resolve_document_label(
                    getattr(chosen_doc, "metadata", None),
                    fallback_label="Document 1",
                )
            except Exception:
                doc_label_for_hint = None

        # For clear "when / متى" questions where we can reliably extract a
        # concrete date from the retrieved documents, short-circuit and answer
        # directly rather than delegating to the LLM. This ensures deterministic
        # behavior even when conversation history might bias the model toward
        # "unknown" answers. For "why" questions we prefer to pass the hint into
        # the LLM so it can clean up / enrich the answer.
        if direct_hint and question_type == "when":
            has_arabic = bool(re.search(r"[\u0600-\u06FF]", query or ""))
            if doc_label_for_hint:
                prefix_ar = f'وفقاً للمستند "{doc_label_for_hint}"، '
                prefix_en = f'According to the document "{doc_label_for_hint}", '
            else:
                prefix_ar = "وفقاً للمستندات، "
                prefix_en = "According to the documents, "

            if has_arabic:
                answer_text = f"{prefix_ar}كان ذلك في {direct_hint}."
            else:
                answer_text = f"{prefix_en}this occurred on {direct_hint}."
            return answer_text, None, None

        return await self.generate_rag_answer_from_documents(
            retrieved_documents=retrieved_documents or [],
            query=query,
            chat_messages=chat_messages,
            stream=stream,
            collector=collector,
            asset_labels=asset_labels,
            asset_labels_by_name=asset_labels_by_name,
            direct_hint=direct_hint,
        )

    async def generate_rag_answer_from_documents(self,
                            retrieved_documents: List[Any],
                            query: str,
                            chat_messages: Optional[List[Dict[str, str]]] = None,
                            stream: bool = False, collector: Optional[dict] = None,
                            asset_labels: Optional[Dict[int, str]] = None,
                            asset_labels_by_name: Optional[Dict[str, str]] = None,
                            direct_hint: Optional[str] = None):
        
        answer_or_stream, full_prompt, chat_history = None, None, None

        if not retrieved_documents or len(retrieved_documents) == 0:
            return answer_or_stream, full_prompt, chat_history
        
        # step2: Select evidence documents and construct LLM prompt
        system_prompt = self.template_parser.get("rag", "system_prompt")

        # Prefer a smaller set of evidence documents when we have a direct_hint,
        # so the model focuses on the most relevant sentences instead of all
        # retrieved context.
        evidence_documents: List[Any] = list(retrieved_documents[:EVIDENCE_DOC_LIMIT])
        if direct_hint and retrieved_documents:
            def normalize_for_match(text: str) -> str:
                t = (text or "").lower()
                # Basic Arabic normalization + whitespace collapse.
                t = re.sub(r"[ًٌٍَُِّْـ]", "", t)
                t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
                t = t.replace("ى", "ي").replace("ة", "ه")
                t = re.sub(r"\s+", " ", t)
                return t.strip()

            hint_norm = normalize_for_match(direct_hint)
            docs_with_hint: List[Any] = []
            for doc in retrieved_documents:
                text_value = getattr(doc, "text", "") or ""
                if not text_value:
                    continue
                if hint_norm and hint_norm in normalize_for_match(text_value):
                    docs_with_hint.append(doc)
            if docs_with_hint:
                evidence_documents = docs_with_hint[:EVIDENCE_DOC_LIMIT]

        document_sections = []
        for idx, doc in enumerate(evidence_documents):
            chunk_text = self.generation_client.process_text(doc.text)
            doc_label = self._resolve_document_label(
                getattr(doc, "metadata", None),
                fallback_label=f"Document {idx + 1}",
                asset_labels=asset_labels,
                asset_labels_by_name=asset_labels_by_name,
            )
            section = self.template_parser.get("rag", "document_prompt", {
                    "doc_label": doc_label,
                    "chunk_text": chunk_text,
            }) or f"## Document: {doc_label}\n### Content: {chunk_text}"
            document_sections.append(section)

        documents_prompts = "\n".join(document_sections)

        hint_section = ""
        if direct_hint:
            hint_section = self.template_parser.get("rag", "hint_section", {
                "hint": direct_hint,
            }) or ("\n\n# Direct candidate answer extracted from documents:\n"
                   f"{direct_hint}\n")
            documents_prompts = documents_prompts + "\n" + hint_section

        footer_prompt = self.template_parser.get("rag", "footer_prompt", {
            "query": query
        })

        # step3: Construct Generation Client Prompts
        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        if chat_messages:
            trimmed_messages = chat_messages[-5:]

            if len(trimmed_messages) > 2:
                earlier_messages = trimmed_messages[:-2]
                prioritized_messages = trimmed_messages[-2:]
            else:
                earlier_messages = []
                prioritized_messages = trimmed_messages

            for message in earlier_messages:
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("prompt", "")),
                        role=self.generation_client.enums.USER.value,
                    )
                )
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("answer", "")),
                        role=self.generation_client.enums.ASSISTANT.value,
                    )
                )

            for message in prioritized_messages:
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("prompt", "")),
                        role=self.generation_client.enums.USER.value,
                    )
                )
                chat_history.append(
                    self.generation_client.construct_prompt(
                        prompt=self.generation_client.process_text(message.get("answer", "")),
                        role=self.generation_client.enums.ASSISTANT.value,
                    )
                )

        full_prompt = "\n\n".join([ documents_prompts,  footer_prompt])

        if stream:
            answer_or_stream = self.generation_client.generate_text_stream(
                prompt=full_prompt,
                chat_history=chat_history,
                collector=collector
            )
        else:
            answer_or_stream = self.generation_client.generate_text(
                prompt=full_prompt,
                chat_history=chat_history
            )

        return answer_or_stream, full_prompt, chat_history
    
    def summarize_chunks(self, chunks: List[DataChunk], focus: Optional[str] = None,
                         max_output_tokens: Optional[int] = None,
                         asset_labels: Optional[Dict[int, str]] = None,
                         asset_labels_by_name: Optional[Dict[str, str]] = None,
                         stream: bool = False,
                         collector: Optional[Dict[str, list]] = None):
        if not chunks or len(chunks) == 0:
            return None, None

        system_prompt = self.template_parser.get("summary", "system_prompt") or (
            "You are an assistant that condenses provided content into a clear, concise summary."
        )

        document_sections = []
        for idx, chunk in enumerate(chunks):
            chunk_text = self.generation_client.process_text(chunk.chunk_text)
            fallback_label = f"Document {chunk.chunk_order if chunk.chunk_order else idx + 1}"
            doc_label = self._resolve_document_label(
                getattr(chunk, "chunk_metadata", None),
                fallback_label=fallback_label,
                asset_labels=asset_labels,
                asset_labels_by_name=asset_labels_by_name,
                asset_id_hint=getattr(chunk, "chunk_asset_id", None),
            )
            section = self.template_parser.get("summary", "document_prompt", {
                "doc_label": doc_label,
                "chunk_text": chunk_text,
            }) or f"## Document: {doc_label}\n{chunk_text}"
            document_sections.append(section)

        documents_prompts = "\n".join(document_sections)

        default_focus = self.template_parser.get("summary", "default_focus") or "Provide a concise summary that highlights the key ideas and critical details."

        summary_prompt = self.template_parser.get("summary", "summary_prompt", {
            "documents": documents_prompts,
            "focus": focus or default_focus,
        }) or "\n".join([
            "Summarize the following documents.",
            documents_prompts,
            "",
            focus or default_focus
        ])

        chat_history = [
            self.generation_client.construct_prompt(
                prompt=system_prompt,
                role=self.generation_client.enums.SYSTEM.value,
            )
        ]

        if stream:
            summary_stream = self.generation_client.generate_text_stream(
                prompt=summary_prompt,
                chat_history=chat_history,
                max_output_tokens=max_output_tokens,
                collector=collector,
            )
            return summary_stream, summary_prompt

        summary = self.generation_client.generate_text(
            prompt=summary_prompt,
            chat_history=chat_history,
            max_output_tokens=max_output_tokens
        )

        return summary, summary_prompt
