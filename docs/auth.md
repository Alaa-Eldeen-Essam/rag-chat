# Auth & Roles

This project uses HTTP Basic authentication and a simple role model (`user` vs `admin`) to control access to endpoints and UI sections.

## Authentication

- Every protected backend route expects:

```http
Authorization: Basic base64("username:password")
```

- The frontend stores the username/password in a small settings context (`SettingsContext`) and sends the `Authorization` header on every request.
- On login, the frontend calls `GET /api/v1/users/me` to validate credentials and to discover:
  - `id` – stored as `currentUserId`
  - `is_admin` – stored as `currentUserIsAdmin`
  - `department`

If the backend returns `401` at any point, the frontend treats the session as invalid and redirects to the login page.

## Roles & Capabilities

### Normal users

- Can:
  - Upload files they own (with `visibility=private|department|global`).
  - Process and index their own files.
  - Run RAG queries and summaries against any files they have access to.
  - View their own stats via `GET /api/v1/stats/user`.
  - See the `Chat`, `Stats`, `Summaries`, and `Files` pages.
- Cannot:
  - Access `GET /api/v1/stats/system` or `/api/v1/stats/users*`.
  - Access `/api/v1/users/*` admin management routes.
  - Delete global files owned by other users.

### Admins

- Can do everything a normal user can, plus:
  - Manage users:
    - `POST /api/v1/users/create`
    - `GET /api/v1/users`
    - `PATCH /api/v1/users/...`
    - `DELETE /api/v1/users/users/{user_id}`
  - View system stats:
    - `GET /api/v1/stats/system`
    - `GET /api/v1/stats/users`
    - `GET /api/v1/stats/users/{user_id}`
  - Delete any asset (including global files) as part of governance.

The frontend hides admin-only pages (Admin Users, Admin Files, System/Users tabs in Stats) when `currentUserIsAdmin` is `false`, but the backend is the final authority (admin-only endpoints still validate role).

## Registration & Default Projects

- Public registration: `POST /api/v1/users/register`.
  - Creates a non-admin user with default department `Global`.
- Admin creation: `POST /api/v1/users/create`.
  - Admin can pick `role = "user" | "admin"` and department.
  - Admins default to department `Admins` if none is provided.

On login, the frontend sets:

- `defaultProjectId = String(currentUser.id)` – each user effectively has their own project id.
- When new content is uploaded or RAG is run, that project id is used for project-specific operations; RAG retrieval itself can pull from all accessible projects (own + department + global), but the main project id is per-user.

## Security Notes

- Global files:
  - Any authenticated user may read/search global content according to visibility rules.
  - Only the owner and admins may delete global files.
- Stats:
  - `/api/v1/stats/system` and `/api/v1/stats/users*` are admin-only and return 403 for normal users.
- Feedback:
  - `/api/v1/stats/feedback` ensures that a user can only attach feedback to their own chat messages (`ChatHistory.user_id == current_user.id`).

