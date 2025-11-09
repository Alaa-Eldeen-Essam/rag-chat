# API Reference

All endpoints are served from the FastAPI application root. Unless stated otherwise, authenticated routes expect **HTTP Basic Auth** credentials in the `Authorization` header. Successful responses include a `signal` field (see `src/models/enums/ResponseEnums.py`) that can be used for client-side branching.

## Authentication

```
Authorization: Basic base64("username:password")
```

- Create users with `POST /api/v1/users/register`.
- Promote to admin with `POST /api/v1/users/admin` (requires an authenticated admin caller).
- The `/api/v1` root and `/api/v1/users/register` endpoints are public; everything else requires authentication.

---

## Base Routes

| Method | Path        | Auth | Description |
|--------|-------------|------|-------------|
| GET    | `/api/v1/`  | No   | Health/info endpoint returning the app name and version from `.env`.

**Sample response**
```json
{
  "app_name": "mini-RAG-Alaa",
  "app_version": "0.1"
}
```

---

## User Routes (`/api/v1/users`)

### POST `/api/v1/users/register`
- **Auth:** None
- **Body:**
```json
{
  "username": "demo",
  "password": "minLength6"
}
```
- **Response:** `201 Created` with the new user or `409` if the username already exists.

### POST `/api/v1/users/admin`
- **Auth:** Basic (must already be an admin)
- **Body:** Same schema as register.
- **Response:** `201 Created` with admin user info, `403` if the caller is not admin.

---

## Data Ingestion Routes (`/api/v1/data`)

### POST `/upload/{project_id}`
- **Auth:** Basic
- **Body:** `multipart/form-data`
  - `file` (required): PDF, TXT, DOCX, HTML, PNG/JPG/TIFF.
  - `is_private` (bool, default `true`).
  - `doc_type` (string, default `"general"`).
- **Behavior:** Stores the file under the project, records metadata in `assets` table.
- **Response:**
```json
{
  "signal": "file_upload_success",
  "file_id": "<asset_id>",
  "stored_file_name": "generated_guid.pdf",
  "original_file_name": "MyDoc.pdf",
  "is_private": true,
  "doc_type": "general"
}
```

### POST `/process/{project_id}`
- **Auth:** Basic
- **Body (`application/json`)**
```json
{
  "file_id": "optional_stored_filename",
  "chunk_size": 400,
  "overlap_size": 20,
  "do_reset": 1,
  "is_private": true
}
```
- **Behavior:** Loads file(s) from the project, extracts text, chunks it, and writes into `chunks` table. When `do_reset=1`, existing chunks for the project are cleared before inserting.
- **Success Response:**
```json
{
  "signal": "processing_success",
  "inserted_chunks": 128,
  "processed_files": 2
}
```
- **Errors:** `400 processing_failed` when extraction produced no text, `404/403` if the project or file is inaccessible.

### GET `/assets/{project_id}`
- **Auth:** Basic
- **Description:** Lists all accessible assets for the project.
- **Sample response:**
```json
{
  "signal": "file_list_success",
  "assets": [
    {
      "asset_id": 12,
      "project_id": 1,
      "user_id": 7,
      "name": "uw8fanbg0a1a_AlaaEldeen1.pdf",
      "original_name": "AlaaEldeen (1).pdf",
      "doc_type": "general",
      "is_private": true,
      "size": 523881,
      "created_at": "2025-02-18T11:12:21.315241",
      "updated_at": null
    }
  ]
}
```

### DELETE `/assets/{asset_id}`
- **Auth:** Basic (must own the asset or have permission)
- **Description:** Deletes an uploaded asset and its associated chunks.
- **Responses:**
  - `200` + `file_delete_success` on success.
  - `404 file_id_error` if the asset does not exist.
  - `403 access_forbidden` if the asset belongs to another private project.

### POST `/upload/process/index/{project_id}`
- **Auth:** Basic
- **Body:** `multipart/form-data`
  - `file` (required): same formats as `/upload`.
  - `chunk_size` (int, default `100`)
  - `overlap_size` (int, default `20`)
  - `do_reset` (int, default `0`) – when `1`, drops and recreates the project’s vector collection before indexing the new chunks.
  - `is_private` (bool, default `true`), `doc_type` (string)
- **Description:** Convenience endpoint that uploads a file, processes it into chunks, stores those chunks in Postgres, and immediately indexes them into the configured vector DB (pgvector or Qdrant). If vector indexing fails, it rolls back the asset/chunks and returns an error signal.
- **Success response:**
```json
{
  "signal": "insert_into_vectordb_success",
  "asset_id": 42,
  "stored_file_name": "uw8fanbg0a1a_AlaaEldeen1.pdf",
  "original_file_name": "Alaa Eldeen (1).pdf",
  "chunks_created": 14,
  "indexed_chunks": 14,
  "collection_name": "collection_1024_1"
}
```

---

## NLP & Retrieval Routes (`/api/v1/nlp`)

### POST `/index/push/{project_id}`
- **Auth:** Basic
- **Body:**
```json
{
  "do_reset": 0,
  "asset_name": "uw8fanbg0a1a_AlaaEldeen1.pdf"
}
```
- **Description:** Streams processed chunks into the configured vector DB (pgvector/Qdrant). When `asset_name` is provided, only that stored file is indexed; otherwise the entire project is re-indexed. Setting `do_reset=1` drops and recreates the collection before inserting (use with care if you’re targeting a single file).
- **Response:** `insert_into_vectordb_success` plus `inserted_items_count`.

### GET `/index/info/{project_id}`
- Returns Qdrant collection metadata (vector size, record counts, etc.) with `vectordb_collection_retrieved` signal.

### POST `/index/search/{project_id}`
- **Body (`SearchRequest`):**
```json
{
  "text": "find arabic policy",
  "limit": 5
}
```
- **Result:** `vectordb_search_success` plus an array of `{ "text": ..., "score": ..., "metadata": {...} }`.

### POST `/index/answer/{project_id}`
- **Body (`SearchRequest` extended):**
```json
{
  "text": "Summarize the CNN exam PDF",
  "limit": 5,
  "conversation_id": 3,
  "model": "best",
  "asset_id": 12,
  "stream": true
}
```
- **Description:** Runs the full RAG pipeline (retrieval → LLM). **Streaming is enabled by default**; include `"stream": false` if you need the legacy blocking response. Automatically stores the conversation history.
- **Response (non-streaming):**
```json
{
  "signal": "rag_answer_success",
  "conversation_id": 3,
  "conversation_title": "Summarize the CNN exam PDF",
  "model": "best",
  "model_id": "command-r7b-arabic:7b-02-2025-q8_0",
  "answer": "...",
  "full_prompt": "## Document: AlaaEldeen (1).pdf..."
}
```
- **Streaming mode:** When streaming, the endpoint returns `text/event-stream` chunks (`rag_answer_stream_start`, repeated `rag_answer_stream_delta`, followed by `rag_answer_success`/`rag_answer_error`) and persists history after the final chunk.

### POST `/summary/{project_id}`
- **Body (`SummarizeRequest`):**
```json
{
  "file_id": "uw8fanbg0a1a_AlaaEldeen1.pdf",
  "max_chunks": 0,
  "model": "fast",
  "focus": "Highlight key decisions",
  "max_output_tokens": 512,
  "stream": true
}
```
- **Description:** Fetches processed chunks (optionally filtered by file) and streams the summary tokens in real time by default (events: `summary_stream_start`, multiple `summary_stream_delta`, and a final `summary_generation_success`). You may also pass `"model": "best" | "fast" | "thinking"` to target a specific Ollama client. Send `"stream": false` to receive a single JSON response instead.
- **Final Response:** Whether streamed or blocking, the last payload includes `summary_generation_success`, the full summary text, chunks used, and the rendered prompt.

### Conversations & Metadata

| Method | Path | Description |
|--------|------|-------------|
| GET `/api/v1/nlp/conversations` | Lists the authenticated user’s conversations. |
| GET `/api/v1/nlp/conversations/{conversation_id}/history?limit=5` | Returns chat turns for a conversation (most recent `limit` or the full history). |
| GET `/api/v1/nlp/doc-types` | Returns the unique document-type labels the current user has uploaded. |

Each of these routes returns a `signal` (`conversations_fetch_success`, `conversation_history_success`, or `vectordb_search_success`) plus the corresponding payloads.

---

## Statistics Routes (`/api/v1/stats`)

### GET `/user`
- **Auth:** Basic
- **Description:** Returns detailed analytics for the calling user (query totals, response-time averages, usage heatmaps, preferred document types/models, etc.).
- **Response Signal:** `user_stats_success`.

### GET `/admin`
- **Auth:** Basic (admin only)
- **Query Params:** `user_id` (optional) — include to append per-user stats.
- **Description:** Returns global platform analytics plus optional drill-down for a specific user.
- **Response Signal:** `admin_stats_success`; includes a `global` object and, if requested, a `user` object.

---

## Conversations Helper Routes (`/api/v1/nlp`)

These endpoints support client UI state:

1. `GET /api/v1/nlp/conversations` – list sessions.
2. `GET /api/v1/nlp/doc-types` – filter options for retrieval.
3. `GET /api/v1/nlp/conversations/{conversation_id}/history` – load message history (supports `limit` query param).

All three require Basic Auth and reuse the signals described above.

---

## Example Flow

1. **Upload** a PDF (`POST /api/v1/data/upload/{project}`) → store the returned `file_id`.
2. **Process** it (`POST /api/v1/data/process/{project}`) with desired chunk/overlap sizes.
3. **Index** chunks (`POST /api/v1/nlp/index/push/{project}`) so they are searchable.
4. **Ask** a question (`POST /api/v1/nlp/index/answer/{project}`) or request a **summary** (`POST /api/v1/nlp/summary/{project}`).
5. **Review** conversation history or stats as needed.

Use the `signal` field to distinguish success vs. common failure scenarios (`access_forbidden`, `project_not_found`, `processing_failed`, etc.).
