from .BaseController import BaseController
from models.db_schemes import Project, DataChunk
from stores.llm.LLMEnums import DocumentTypeEnum
from typing import List, Optional, Dict
import json

class NLPController(BaseController):

    def __init__(self, vectordb_client, generation_client, 
                 embedding_client, template_parser):
        super().__init__()

        self.vectordb_client = vectordb_client
        self.generation_client = generation_client
        self.embedding_client = embedding_client
        self.template_parser = template_parser

    def create_collection_name(self, project_id: str):
        return f"collection_{project_id}".strip()
    
    def reset_vector_db_collection(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        return self.vectordb_client.delete_collection(collection_name=collection_name)
    
    def get_vector_db_collection_info(self, project: Project):
        collection_name = self.create_collection_name(project_id=project.project_id)
        collection_info = self.vectordb_client.get_collection_info(collection_name=collection_name)

        return json.loads(
            json.dumps(collection_info, default=lambda x: x.__dict__)
        )
    
    def index_into_vector_db(self, project: Project, chunks: List[DataChunk],
                                   chunks_ids: List[int], 
                                   do_reset: bool = False):
        
        # step1: get collection name
        collection_name = self.create_collection_name(project_id=project.project_id)

        # step2: manage items
        texts = [ c.chunk_text for c in chunks ]
        metadata = [ c.chunk_metadata for c in  chunks]
        vectors = [
            self.embedding_client.embed_text(text=text, 
                                             document_type=DocumentTypeEnum.DOCUMENT.value)
            for text in texts
        ]

        # step3: create collection if not exists
        _ = self.vectordb_client.create_collection(
            collection_name=collection_name,
            embedding_size=self.embedding_client.embedding_size,
            do_reset=do_reset,
        )

        # step4: insert into vector db
        _ = self.vectordb_client.insert_many(
            collection_name=collection_name,
            texts=texts,
            metadata=metadata,
            vectors=vectors,
            record_ids=chunks_ids,
        )

        return True

    def search_vector_db_collection(self, project: Project, text: str, limit: int = 10,
                                    doc_types: Optional[List[str]] = None):

        # step1: get collection name
        collection_name = self.create_collection_name(project_id=project.project_id)

        # step2: get text embedding vector
        vector = self.embedding_client.embed_text(text=text, 
                                                 document_type=DocumentTypeEnum.QUERY.value)

        if not vector or len(vector) == 0:
            return False

        # step3: do semantic search
        results = self.vectordb_client.search_by_vector(
            collection_name=collection_name,
            vector=vector,
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
                return filtered_results
            return []

        return results
    
    def answer_rag_question(self, project: Project, query: str, limit: int = 10,
                            chat_messages: Optional[List[Dict[str, str]]] = None,
                            stream: bool = False, collector: Optional[dict] = None,
                            doc_types: Optional[List[str]] = None):
        
        answer_or_stream, full_prompt, chat_history = None, None, None

        # step1: retrieve related documents
        retrieved_documents = self.search_vector_db_collection(
            project=project,
            text=query,
            limit=limit,
            doc_types=doc_types,
        )

        if not retrieved_documents or len(retrieved_documents) == 0:
            return answer_or_stream, full_prompt, chat_history
        
        # step2: Construct LLM prompt
        system_prompt = self.template_parser.get("rag", "system_prompt")

        documents_prompts = "\n".join([
            self.template_parser.get("rag", "document_prompt", {
                    "doc_num": idx + 1,
                    "chunk_text": self.generation_client.process_text(doc.text),
            })
            for idx, doc in enumerate(retrieved_documents)
        ])

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
                         max_output_tokens: Optional[int] = None):
        if not chunks or len(chunks) == 0:
            return None, None

        system_prompt = self.template_parser.get("summary", "system_prompt") or (
            "You are an assistant that condenses provided content into a clear, concise summary."
        )

        documents_prompts = "\n".join([
            self.template_parser.get("summary", "document_prompt", {
                "doc_num": chunk.chunk_order if chunk.chunk_order else idx + 1,
                "chunk_text": self.generation_client.process_text(chunk.chunk_text),
            }) or f"## Document {chunk.chunk_order if chunk.chunk_order else idx + 1}\n{self.generation_client.process_text(chunk.chunk_text)}"
            for idx, chunk in enumerate(chunks)
        ])

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

        summary = self.generation_client.generate_text(
            prompt=summary_prompt,
            chat_history=chat_history,
            max_output_tokens=max_output_tokens
        )

        return summary, summary_prompt
