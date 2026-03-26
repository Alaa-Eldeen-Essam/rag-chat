# Streaming Protocol

The Mini RAG backend uses newline-delimited JSON (NDJSON) over a `ReadableStream` to stream both chat answers and summaries to the frontend. Each line is a complete JSON object with a `signal` field indicating the event type.

## General Pattern

- HTTP response headers:
  - `Content-Type: application/json`
- Body:
  - Text chunks, each chunk may contain zero or more `\n`-separated JSON lines.
  - Clients must accumulate chunk text into a buffer, split on `\n`, and parse each non-empty line with `JSON.parse`.
- Common event structure:

```json
{ "signal": "some_signal_name", "other_fields": "..." }
```

The frontend implements this logic in `frontend/src/lib/streamClient.ts`.

## RAG Answer Streams

Endpoint:

```http
POST /api/v1/nlp/index/answer/{project_id}
```

Typical sequence:

1. `rag_answer_stream_start` – emitted once per request:
   ```json
   {
     "signal": "rag_answer_stream_start",
     "conversation_id": 3,
     "conversation_title": "My conversation",
     "model": "best",
     "model_id": "my-model-id"
   }
   ```
2. Zero or more `rag_answer_stream_delta` events:
   ```json
   {
     "signal": "rag_answer_stream_delta",
     "delta": "partial answer text"
   }
   ```
3. Final `rag_answer_success` (or `rag_answer_error` on failure):
   ```json
   {
     "signal": "rag_answer_success",
     "answer": "full, assembled answer text",
     "conversation_id": 3,
     "conversation_title": "My conversation",
     "document_types": ["general"],
     "model": "best",
     "model_id": "my-model-id",
     "asset_id": 12,
     "message_id": 123
   }
   ```

The frontend:

- Creates an empty assistant message when `rag_answer_stream_start` arrives.
- Appends `delta` strings as `rag_answer_stream_delta` events come in.
- Replaces the content with `answer` from `rag_answer_success` as the final state.
- Uses `message_id` to attach feedback via `POST /api/v1/stats/feedback`.

If `no_answer_from_docs` is detected server-side, the stream will emit a single fallback answer with the same pattern, but the answer content is an “I don’t know / no docs” style message and `fallback_used=true` is recorded in `ChatHistory`.

## Summary Streams

Endpoint:

```http
POST /api/v1/nlp/summary/{project_id}
```

Typical sequence:

1. `summary_stream_start`:
   ```json
   {
     "signal": "summary_stream_start",
     "file_id": 12,
     "model": "fast",
     "model_id": "my-fast-model-id"
   }
   ```
2. Zero or more `summary_stream_delta` events:
   ```json
   {
     "signal": "summary_stream_delta",
     "delta": "partial summary text"
   }
   ```
3. Final `summary_generation_success` (or `summary_generation_error`):
   ```json
   {
     "signal": "summary_generation_success",
     "summary": "full, assembled summary text",
     "file_id": 12,
     "focus": "optional focus text",
     "max_output_tokens": 1024,
     "model": "fast",
     "model_id": "my-fast-model-id"
   }
   ```

The frontend’s Summary panel:

- Starts a new summary card on `summary_stream_start`.
- Appends deltas into the visible summary text.
- Marks the summary as “saved” and shows metadata once `summary_generation_success` arrives.

## Error Signaling

- For RAG:
  - Final event may have `signal = "rag_answer_error"` with error details.
  - The frontend should keep any partial content visible and allow retry.
- For Summary:
  - Final event may have `signal = "summary_generation_error"`.
  - The frontend should show an error message and let the user retry.

Any non-2xx HTTP status (e.g., 4xx/5xx) should be treated as a hard error; the client will not receive a well-formed stream in that case and should display an appropriate message.

