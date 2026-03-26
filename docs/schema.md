# Data Model & Table Relationships

This document summarizes the core database tables and how they relate to each other. It is based on the SQLAlchemy models under `src/models/db_schemes/minirag/schemes/`.

## Core Entities

### User

File: `user.py`

- Fields:
  - `id`
  - `username`
  - `password_hash`
  - `is_admin` (bool)
  - `department` (string, default `"Global"`)
  - `created_at`, `last_login`
- Relationships:
  - `projects`: one-to-many with `Project`
  - `assets`: one-to-many with `Asset`
  - `chat_history`: one-to-many with `ChatHistory`
  - `conversations`: one-to-many with `ChatConversation`
  - `summaries`: one-to-many with `SummaryRecord`

**Usage:** Users own projects and assets, initiate chat conversations, and request summaries. Role and department drive access control and admin capabilities.

### Project

File: `project.py`

- Fields:
  - `project_id`
  - `project_user_id` (FK → `User.id`)
  - `project_is_private`
  - `project_uuid`, timestamps
- Relationships:
  - `user`: many-to-one → `User`
  - `assets`: one-to-many → `Asset`
  - `chunks`: one-to-many → `DataChunk`
  - `summaries`: one-to-many → `SummaryRecord`

**Usage:** A logical container for assets and chunks. The frontend typically uses one project per user (`defaultProjectId = user.id`), but RAG retrieval can span all accessible projects.

### Asset (Document)

File: `asset.py`

- Fields:
  - `asset_id`
  - `asset_uuid`
  - `asset_type` (e.g. `"file"`)
  - `asset_name` (stored file name)
  - `asset_size`
  - `asset_config` (JSONB, includes `original_filename`)
  - `asset_document_type` (e.g. `"general"`, `"law"`, `"finance"`)
  - `asset_project_id` (FK → `Project.project_id`)
  - `asset_user_id` (FK → `User.id`)
  - `asset_is_private` (legacy boolean)
  - `asset_visibility` (`"private" | "department | "global"`)
  - `asset_department` (for department-visible assets)
  - timestamps
- Relationships:
  - `project`: many-to-one → `Project`
  - `user`: many-to-one → `User`
  - `chunks`: one-to-many → `DataChunk`
  - `summaries`: one-to-many → `SummaryRecord`

**Usage:** Represents an uploaded document. Visibility and department fields determine who can see/use it in RAG and summaries. Deleting an asset also prunes related chunks and vector records.

### DataChunk

File: `datachunk.py`

- Fields:
  - `chunk_id`, `chunk_uuid`
  - `chunk_text`
  - `chunk_metadata` (JSONB; includes `doc_type`, `asset_id`, filenames, etc.)
  - `chunk_order`
  - `chunk_project_id` (FK → `Project.project_id`)
  - `chunk_asset_id` (FK → `Asset.asset_id`)
  - timestamps
- Relationships:
  - `project`: many-to-one → `Project`
  - `asset`: many-to-one → `Asset`

**Usage:** Holds text chunks for retrieval and summarization. These are also mirrored in the vector database keyed by chunk id and project.

### ChatConversation

File: `conversation.py`

- Fields:
  - `conversation_id`
  - `conversation_user_id` (FK → `User.id`)
  - `conversation_title`
  - timestamps
- Relationships:
  - `user`: many-to-one → `User`
  - `history`: one-to-many → `ChatHistory` (cascade delete)

**Usage:** Top-level grouping of chat messages. Used for the conversation sidebar and loading history into the Chat page.

### ChatHistory

File: `chat_history.py`

- Fields:
  - `id`
  - `user_id` (FK → `User.id`)
  - `conversation_id` (FK → `ChatConversation.conversation_id`)
  - `prompt`
  - `answer`
  - `timestamp`
  - `response_time_ms`
  - `model_key` (e.g. `"best"`, `"fast"`)
  - `doc_types` (JSONB list of doc types used)
  - `rating` (optional, 1–5)
  - `is_helpful` (optional bool)
  - `fallback_used` (optional bool)
  - `retrieved_chunks` (optional int)
  - `retrieved_doc_types` (JSONB list)
  - `retrieved_asset_ids` (JSONB list)
- Relationships:
  - `user`: many-to-one → `User`
  - `conversation`: many-to-one → `ChatConversation`

**Usage:** Each entry represents a single RAG turn (prompt + answer). It powers:

- Conversation history views.
- Latency and usage statistics.
- Feedback-based metrics (ratings, helpful vs unhelpful).
- Retrieval analytics (chunks per query, doc type and asset usage).

### SummaryRecord

File: `summary.py`

- Fields:
  - `summary_id`
  - `project_id` (FK → `Project.project_id`)
  - `user_id` (FK → `User.id`)
  - `asset_id` (FK → `Asset.asset_id`, optional)
  - `request_payload` (JSONB; model, focus, max_chunks, etc.)
  - `chunk_ids` (JSONB; ids of chunks used)
  - `chunk_count`
  - `summary_text`
  - `prompt_text`
  - `max_output_tokens`
  - `created_at`
- Relationships:
  - `project`: many-to-one → `Project`
  - `user`: many-to-one → `User`
  - `asset`: many-to-one → `Asset`

**Usage:** Stores generated summaries so they can be listed and revisited. Stats use this to compute summary-related activity.

## How Changes Propagate

- Deleting a **User**:
  - May orphan or cascade related objects depending on DB configuration; user management endpoints ensure that deletes are intentional and safe.
- Deleting a **Project**:
  - Cascades to `chunks`, `assets`, and `summaries` linked to that project.
  - The vector DB collection for the project is typically dropped or reset via the NLP controller.
- Deleting an **Asset**:
  - Removes associated `DataChunk` rows.
  - Triggers deletion of corresponding vector records for those chunk ids.
  - Global visibility affects who can use the document, but deletion is restricted to the owner and admins.
- Adding feedback to **ChatHistory**:
  - Feeds into stats aggregations (quality and content risk).
  - Combined with `retrieved_asset_ids`, this determines which documents are underperforming.

Understanding these relationships helps when:

- Writing new migrations (Alembic).
- Adding new features that depend on existing data (e.g., per-asset dashboards).
- Debugging permission or visibility issues (e.g., why a user can/can’t see a document in RAG).

