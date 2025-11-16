# Stats & Analytics Guide

Mini RAG exposes several statistics endpoints and a rich Stats UI to help you understand how the system is being used and where to improve content.

## Endpoints Overview

- `GET /api/v1/stats/user` – per-user stats (for the current user).
- `GET /api/v1/stats/system` – system-wide stats (admins only).
- `GET /api/v1/stats/users` – paginated per-user overview (admins only).
- `GET /api/v1/stats/users/{user_id}` – detailed stats for a specific user (admins only).
- `POST /api/v1/stats/feedback` – attach ratings/feedback to individual answers.

## Key Metrics

### Per-User (`/stats/user`)

- **Totals**
  - `queries`: number of RAG questions asked.
  - `conversations`: distinct chat conversations.
  - `documents`: uploaded documents owned by the user.
- **Response Times**
  - `average_ms`: average model response time.
  - `total_ms`: total time spent answering the user’s queries.
- **Time-Based Usage**
  - Daily counts and weekly trend of queries.
  - Peak usage hours.
- **Model Preferences**
  - How often each model key (`best`, `fast`, `thinking`, etc.) is used.
- **Query Topics**
  - Top keywords extracted from prompts (after multilingual stopword filtering).
- **Quality**
  - `average_rating`: average of 1–5 ratings.
  - `helpful_count` / `unhelpful_count`: feedback counts.
  - `fallback_count`: how many times the system had to fall back to an “I don’t know” answer.
- **Retrieval**
  - `average_retrieved_chunks`: average number of chunks per query.
  - `chunk_histogram`: distribution (0, 1–5, 6–10, >10).
  - `doc_type_hits`: which doc types actually contributed to answers.
- **Engagement**
  - `conversation_length_buckets`: number of conversations with 1–3, 4–10, and >10 messages.

### System-Wide (`/stats/system`)

On top of the per-user metrics, the system stats include:

- **Global Totals**
  - `users`, `documents`, `conversations`, `queries`.
- **Latency Percentiles**
  - `latency_percentiles`: P50, P90, P95, P99 response times.
- **Requests Per Hour**
  - `requests_per_hour`: list of `{ hour, model, count }` over the last 24 hours.
- **Engagement**
  - `dau`: daily active users.
  - `wau`: weekly active users.
  - `new_users_last_7_days`.
- **Department & Visibility**
  - `queries_by_department`: mapping department → query count.
  - `usage_by_visibility`: counts of documents by visibility (`private | department | global`).
- **Quality (Global)**
  - `average_rating`: global average rating.
  - `fallback_count`: total number of fallback answers.
- **Retrieval (Global)**
  - `average_retrieved_chunks` and `chunk_histogram`.
  - `doc_type_hits`: which doc types are being used across the entire system.
- **Content Risk**
  - `content_risk`: a list of documents with:
    - `asset_id`, `name`, `doc_type`, `visibility`, `department`
    - `queries`, `avg_rating`, `fallback_rate`

This table is ideal for spotting documents that are heavily used but poorly performing (low rating or high fallback rate).

## How to Read the Stats UI

### My Stats tab

- Use **Totals** to understand your own activity.
- Look at **Weekly Trend** to see how your usage changes over time.
- Check **Model Usage** to see if you are leaning on a single model too much (e.g., always “fast”).
- Use **Average Rating** and **Fallback Answers** to decide whether your prompts or documents need improvement.
- Use **Avg Retrieved Chunks** and **Conversation Lengths** to see how “deep” your typical queries and sessions go.

### System tab (Admins)

- **User / Doc / Query totals** give a quick platform health snapshot.
- **DAU / WAU / New Users (7d)** tell you whether adoption is growing.
- **Documents by Type** and **Global Model Usage** highlight what content and models are most used.
- **Queries by Department** and **Documents by Visibility** show how different teams are using the system and how content is shared.
- **Content Risk Documents**:
  - Sort by `queries` to see the most important documents.
  - Look at `avg_rating` and `fallback_rate` to find:
    - High usage + low rating → docs to revise or augment.
    - High usage + high fallback → missing coverage or indexing problems.

### Users tab (Admins)

- Combine per-user stats with System stats:
  - Identify power users or departments.
  - Spot users with many queries but high latency or low ratings.
  - Target training or onboarding based on usage patterns.

## Feedback Loop

The feedback endpoint (`POST /api/v1/stats/feedback`) and the content risk table form a closed loop:

1. Users mark answers as **Helpful / Not helpful**.
2. Ratings are stored in `ChatHistory`.
3. Stats aggregate these ratings per user and per document.
4. Admins use `content_risk` to prioritize which documents or doc types to improve.

Over time this allows you to iteratively increase the overall quality of your knowledge base and RAG answers.

