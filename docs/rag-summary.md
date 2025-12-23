# RAG & Summary Pipelines

This document describes how data flows through the system for retrieval-augmented generation (RAG) and document summaries.

## High-Level Flow

1. **Upload**
   - `POST /api/v1/data/upload/{project_id}` or
   - `POST /api/v1/data/upload/process/index/{project_id}` (single file) or
   - `POST /api/v1/data/upload/process/index/batch/{project_id}` (batch).
2. **Process**
   - `POST /api/v1/data/process/{project_id}` (if you upload without immediate processing).
   - Extracts text, chunks it, stores in `chunks` table.
3. **Index**
   - `POST /api/v1/nlp/index/push/{project_id}` (re-index existing chunks).
   - Or use the combined upload+process+index endpoints above.
4. **Answer**
   - `POST /api/v1/nlp/index/answer/{project_id}`:
     - Retrieves relevant chunks.
     - Builds an LLM prompt.
     - Streams or returns a final answer.
     - Logs `ChatHistory` and updates `ChatConversation`.
5. **Summary**
   - `POST /api/v1/nlp/summary/{project_id}`:
     - Fetches chunks for a specific file.
     - Streams a summary.
     - Persists a `SummaryRecord`.
6. **Stats**
   - `GET /api/v1/stats/*`:
     - Aggregates information from `ChatHistory`, `ChatConversation`, `Asset`, `SummaryRecord`, and `User`.

## Multi-Project RAG Search

Although the frontend uses a per-user `defaultProjectId`, the RAG endpoint collects all accessible assets across projects:

- For the current user, it fetches:
  - Private assets they own.
  - Department-visible assets for their department.
  - Global assets.
- Assets are grouped by `asset_project_id`.
- For each project, the backend calls `search_vector_db_collection` with:
  - The query text.
  - Optional `doc_types` filter (from explicit `doc_type` in the request or inferred from the query).
  - Optional `asset_ids` filter (when a single file is targeted).

The retrieved documents from all projects are combined and passed into `generate_rag_answer_from_documents`.

## Doc Type Filters

The RAG request can include:

- `doc_type`: `"general" | "law" | "finance" | "all" | ...`
- If `doc_type="all"` or omitted:
  - A helper may infer doc types from the query text (e.g., if the user writes “in the law docs…”).

The backend uses this to filter retrieved chunks by their `doc_type` metadata before constructing the LLM prompt.

## Summaries

`POST /api/v1/nlp/summary/{project_id}` accepts:

- `file_id`: target asset id.
- `max_chunks`: maximum number of chunks (0 = all).
- `focus`: optional text describing what the summary should focus on.
- `model`: model key (`best | fast | thinking`), defaulting to the global model.
- `max_output_tokens`: soft limit for the summary length.
- `stream`: whether to stream summary tokens.

Flow:

1. Validate access to the target asset using the same visibility rules as RAG.
2. Fetch project chunks for that asset (`ChunkModel`).
3. Call `NLPController.summarize_chunks` with the selected model.
4. If `stream=true`, send `summary_stream_start` followed by `summary_stream_delta` events and a final `summary_generation_success`.
5. Persist the summary in `SummaryRecord` with:
   - `project_id`, `user_id`, `asset_id`
   - `chunk_ids`, `chunk_count`
   - `summary_text`, `prompt_text`, `max_output_tokens`
   - `request_payload` (model, focus, max_chunks, etc.).

The frontend’s Summaries page and Summary panel read from:

- `GET /api/v1/nlp/summary` (list for current user).
- `GET /api/v1/nlp/summary/{summary_id}` (detail view).

