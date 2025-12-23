# Visibility & Access Control

Mini RAG supports three visibility levels for documents (assets), plus per-user departments and role-based checks to determine who can access which content.

## Asset Visibility

Every asset has:

- `asset_visibility`: `"private" | "department" | "global"`
- `asset_department`: optional string (used when `asset_visibility="department"`)
- `asset_user_id`: id of the owner

### private

- Only the owner (`asset_user_id`) and admins can see and use the file.
- RAG queries and summaries for other users will not retrieve chunks from this asset.

### department

- Any user whose `User.department` matches `asset_department` can see and use the file.
- Admins can always access it, regardless of department.
- Owner still has access even if their department changes.

### global

- Any authenticated user can see and use the file in RAG queries and summaries.
- **Deletion is still restricted**:
  - Only the owner and admins may delete a global asset.

The upload endpoints (`/api/v1/data/upload*`) accept:

- `visibility`: `"private" | "department" | "global"` (defaults to `"private"`).
- `department` (optional): overrides the department for department-visible files, otherwise ignored.

## Departments

Users have:

- `User.department` (string, default `"Global"`).
- Admins often belong to a special department such as `"Admins"`.

Department is used to:

- Resolve access for `asset_visibility="department"`.
- Group stats by department in `/api/v1/stats/system`.

### Example

1. User **A** has `department = "Legal"` and uploads a file with:
   - `visibility = "department"`
   - no explicit `department` field
2. The asset is stored with:
   - `asset_visibility = "department"`
   - `asset_department = "Legal"`

Then:

- User **B** with `department = "Legal"` can see and query this file.
- User **C** with `department = "Finance"` cannot.
- Admins can see and query it regardless of department.

## Global Files Across Per-User Projects

Each user effectively has their own primary project id (`defaultProjectId = user.id` on the frontend), but RAG search can span:

- Files in the caller’s project.
- Any global files.
- Department-visible files for the caller’s department.

Backend helper methods (e.g. `get_all_accessible_assets`) enforce visibility rules and return the list of accessible assets for the current user. The RAG endpoint then searches across those assets, grouped by project, so global and department-visible content is available even if it was uploaded under another user’s project.

## OCR-Derived Content

When a file is ingested, the system first tries normal text extraction. If it detects that a PDF contains little or no text, or if the file is an image, it may run OCR (Tesseract) to extract text instead. This does **not** change the asset’s visibility: the same `asset_visibility` / `asset_department` rules apply to OCR-derived chunks.

Chunks produced via OCR are marked in their metadata, which you may see in internal tools:

- `ocr_used: true` – the text for this chunk came from OCR rather than a native text layer.
- `ocr_lang: "eng+ara"` (or similar) – which Tesseract languages were used.

These flags are informational only; they do not affect who can access the chunk, only how the content was obtained.
