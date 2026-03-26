import json
import logging
from typing import List

from stores.llm.LLMEnums import DocumentTypeEnum

logger = logging.getLogger(__name__)


def create_collection_name(controller, project_id: str) -> str:
    return f"collection_{controller.vectordb_client.default_vector_size}_{project_id}".strip()


async def reset_vector_db_collection(controller, project):
    collection_name = create_collection_name(controller, project_id=project.project_id)
    return await controller.vectordb_client.delete_collection(collection_name=collection_name)


async def get_vector_db_collection_info(controller, project):
    collection_name = create_collection_name(controller, project_id=project.project_id)
    collection_info = await controller.vectordb_client.get_collection_info(collection_name=collection_name)

    return json.loads(
        json.dumps(collection_info, default=lambda x: x.__dict__)
    )


async def index_into_vector_db(
    controller,
    project,
    chunks: List,
    chunks_ids: List[int],
    do_reset: bool = False,
):
    # step1: get collection name
    collection_name = create_collection_name(controller, project_id=project.project_id)

    # step2: manage items
    texts = [c.chunk_text for c in chunks]
    metadata = [c.chunk_metadata for c in chunks]
    vectors = controller.embedding_client.embed_text(
        text=texts,
        document_type=DocumentTypeEnum.DOCUMENT.value,
    )

    if not vectors or len(vectors) != len(texts):
        logger.error("Embedding client returned invalid vectors for indexing")
        return False

    # step3: create collection if not exists
    _ = await controller.vectordb_client.create_collection(
        collection_name=collection_name,
        embedding_size=controller.embedding_client.embedding_size,
        do_reset=do_reset,
    )

    # step4: insert into vector db
    _ = await controller.vectordb_client.insert_many(
        collection_name=collection_name,
        texts=texts,
        metadata=metadata,
        vectors=vectors,
        record_ids=chunks_ids,
    )

    # step5: index into search backend (Elasticsearch) when available
    if controller.search_client is not None:
        try:
            index_name = controller.search_client.get_index_name(project.project_id)
            documents = []
            for chunk in chunks:
                meta = chunk.chunk_metadata or {}
                page_value = meta.get("page") or meta.get("page_number")
                original_filename = (
                    meta.get("original_filename")
                    or meta.get("source_name")
                    or ""
                )
                doc = {
                    "chunk_id": getattr(chunk, "chunk_id", None),
                    "project_id": getattr(chunk, "chunk_project_id", None),
                    "asset_id": getattr(chunk, "chunk_asset_id", None),
                    "doc_type": meta.get("doc_type") or meta.get("document_type"),
                    "text": chunk.chunk_text,
                    "page": page_value,
                    "page_number": page_value,
                    "original_filename": original_filename,
                    "metadata": meta,
                }
                documents.append(doc)

            if documents:
                await controller.search_client.index_documents(
                    index_name=index_name,
                    documents=documents,
                )
        except Exception as exc:
            logger.error("Failed to index chunks into search backend: %s", exc)

    return True
