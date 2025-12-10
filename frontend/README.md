# Mini RAG Frontend

React + TypeScript SPA for the local Mini RAG FastAPI backend.

## Tech Stack

- React + TypeScript
- Vite
- Tailwind CSS
- React Router v6
- TanStack React Query
- Fetch API + custom HTTP/streaming clients

## Running the frontend

From the project root:

```bash
cd frontend
npm install
npm run dev
```

By default the app expects the backend at `http://localhost:5000`. The base URL and credentials are managed via a small settings context (`frontend/src/settings/SettingsContext.tsx`) and stored in `localStorage` (except the password, which is only persisted if “remember password” is enabled).

Log in with HTTP Basic Auth credentials that exist in the backend database (or register via the signup page).

## Pages & Layout

- **Login / Signup**
  - Collects username/password.
  - On login, validates via `GET /api/v1/users/me` and stores:
    - Basic Auth credentials
    - `currentUserId`, `currentUserIsAdmin`
    - `defaultProjectId` = user id
- **Chat** (`/chat`)
  - ChatGPT-style RAG UI with:
    - Conversation list, rename/delete.
    - “New Chat” and “Upload & Index File” buttons.
    - Doc-type filter and optional file filter.
    - Streaming assistant responses (NDJSON).
  - Right-hand **Summary** panel to stream document summaries.
- **Stats** (`/stats`)
  - Tabs:
    - *My Stats*: per-user queries, latency, topics, engagement.
    - *System* (admin only): global metrics, DAU/WAU, content risk docs.
    - *Users* (admin only): per-user stats table with search/paging.
- **Admin Users** (`/admin/users`)
  - Only shown for admins.
  - Create users, update role/department, reset password, delete users.
- **Files** / **Admin Files** (`/admin/files`)
  - For admins, labeled *Admin Files*; for normal users, *Files*.
  - Lists accessible assets with search, visibility, delete, “Go to chat” and “Summarize” actions.
- **Summaries** (`/summaries`)
  - Lists saved summaries and shows details for a selected one.

The header contains:
- Model selector (`best | fast | thinking`).
- Doc-type selector.
- Role-aware navigation (admin-only links hidden for normal users).
- Logout button (clears stored credentials and settings).

## Streaming Behaviour

The frontend uses a reusable streaming helper (`frontend/src/lib/streamClient.ts`) to consume NDJSON streams from the backend:

- For **RAG answers** (`POST /api/v1/nlp/index/answer/{project_id}`):
  - Reads `ReadableStream` chunks, decodes to text, splits on `\n`.
  - Parses each JSON line and switches on `signal`:
    - `rag_answer_stream_start`
    - repeated `rag_answer_stream_delta` with `{ "delta": "text" }`
    - final `rag_answer_success` or `rag_answer_error`
  - The client accumulates text deltas into the current assistant message.
  - The final payload includes `conversation_id` and `message_id` so the UI can refresh conversation lists and send feedback.

- For **Summaries** (`POST /api/v1/nlp/summary/{project_id}`):
  - Same pattern with summary-specific signals:
    - `summary_stream_start`
    - `summary_stream_delta`
    - `summary_generation_success` / `summary_generation_error`
  - The Summary panel shows streaming text in a card and marks it as “saved” once the backend persists the summary.

## Role-Based UI Behaviour

The app reads `currentUserIsAdmin` from `GET /api/v1/users/me` and adjusts the UI:

- Normal users:
  - See `Chat`, `Stats`, `Summaries`, and `Files`.
  - Cannot see the Admin Users page.
  - See only assets they are allowed to access (private + department + global).
- Admins:
  - Additionally see `Admin Users` and `Admin Files`.
  - Can view system and per-user stats.
  - Can manage users (create/update/delete) and delete any document (subject to backend rules).

All API calls inject `Authorization: Basic ...` using the credentials from the settings context. A 401 response will cause the frontend to treat the session as invalid and redirect back to the login page.
