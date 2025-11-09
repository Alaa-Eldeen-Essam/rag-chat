import json
import logging
from typing import Any, Dict, List, Optional

from .BaseController import BaseController
from models.db_schemes import DataChunk, Project
from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)

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

    async def search_vector_db_collection(self, project: Project, text: str, limit: int = 10,
                                    doc_types: Optional[List[str]] = None,
                                    asset_ids: Optional[List[int]] = None):

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
                return filtered_results
            return []

        return results
    
    async def answer_rag_question(self, project: Project, query: str, limit: int = 10,
                            chat_messages: Optional[List[Dict[str, str]]] = None,
                            stream: bool = False, collector: Optional[dict] = None,
                            doc_types: Optional[List[str]] = None,
                            asset_ids: Optional[List[int]] = None,
                            asset_labels: Optional[Dict[int, str]] = None,
                            asset_labels_by_name: Optional[Dict[str, str]] = None):
        
        answer_or_stream, full_prompt, chat_history = None, None, None

        # step1: retrieve related documents
        retrieved_documents = await self.search_vector_db_collection(
            project=project,
            text=query,
            limit=limit,
            doc_types=doc_types,
            asset_ids=asset_ids,
        )

        if not retrieved_documents or len(retrieved_documents) == 0:
            return answer_or_stream, full_prompt, chat_history
        
        # step2: Construct LLM prompt
        system_prompt = self.template_parser.get("rag", "system_prompt")

        document_sections = []
        for idx, doc in enumerate(retrieved_documents):
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
