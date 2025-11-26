## Retrieval Pipeline Overview

Mini RAG combines **dense embeddings**, **Elasticsearch lexical/BM25 scoring**, and the
existing **metadata filters** before sending evidence to the LLM. The flow for every
query is:

1. **Dense semantic search** (pgvector) – top‑k chunks by cosine similarity.
2. **Lexical search** (Elasticsearch, BM25‑like) – top‑k chunks by term match using
   analyzers tuned for mixed Arabic/English content.
3. **Hybrid fusion** – chunk scores are normalized per method and merged with a weighted
   sum (default: 0.6 dense / 0.4 lexical). Chunks that appear in either list participate.
4. **Metadata filtering** – the fused list is filtered by `doc_type`, explicit file
   filters, and any keyword filters already supported by `NLPController`.
5. **LLM prompt assembly** – the best chunks (default `EVIDENCE_DOC_LIMIT`) feed the
   template‑specific system/user prompts.

### Dense retrieval

- Stored in `collection_<dim>_<project>` tables (pgvector).  
- Search performed via `search_by_vector` using cosine similarity or dot‑product.
- Results carry the originating `chunk_id` inside `metadata` so they can be merged
  with lexical hits.

### Lexical retrieval (Elasticsearch)

- All chunks are also indexed into an Elasticsearch index
  `<ELASTICSEARCH_INDEX_PREFIX>-chunks` with at least:
  - `chunk_id`, `project_id`, `asset_id`, `doc_type`, `text`,
    `page`/`page_number`, `original_filename`, and the original `metadata`.
- The index uses analyzers suitable for **Arabic and English**:
  - A mixed `text` analyzer (`mixed_ar_en`) with Arabic normalization + Arabic/English
    stemming.
  - Language‑specific sub‑analyzers for `text.ar` and `text.en`.
- Queries from `NLPController.search_vector_db_collection` are converted into a cleaned
  lexical query and executed via Elasticsearch, scoped by `project_id`. The hits are
  converted into `RetrievedDocument` objects and fused with dense pgvector results.
- If Elasticsearch is not configured, the system falls back to Postgres full‑text search
  on a generated `fts` column for backward compatibility.

### Hybrid fusion

- Implemented in `NLPController._fuse_dense_and_lexical_results`.
- Dense/lexical scores are normalized to `[0, 1]` separately and combined:

  ```python
  fused_score = 0.6 * dense_norm + 0.4 * lexical_norm
  ```

- Adjust the ratio inside `_fuse_dense_and_lexical_results` if you want lexical matches
  to carry more/less weight.

### Metadata filters

- Existing filters (doc type, asset IDs, keyword constraints) run on the fused list,
  so hybrid retrieval still respects the UI scope and visibility restrictions.
- Each chunk’s metadata carries a `page_number` (populated during chunking), making it
  easy to surface page references alongside the retrieved excerpt.

---

## Notes on Postgres FTS

Earlier versions used Postgres FTS + a generated `fts` column with a GIN index on each
`collection_*` table. The current setup prefers Elasticsearch for lexical retrieval.

- The vector tables no longer create or manage FTS columns/indexes eagerly.  
- The `search_by_text` method in `PGVectorProvider` remains as a **fallback** for
  deployments that do not configure Elasticsearch.
- If you want to fully retire Postgres FTS for lexical search and reduce write overhead,
  you can safely drop the `fts` column and its GIN index from existing collections:

  ```sql
  DO $$
  DECLARE r RECORD;
  BEGIN
    FOR r IN
      SELECT tablename
      FROM pg_tables
      WHERE tablename LIKE 'collection_%'
    LOOP
      EXECUTE format(
        'ALTER TABLE %I DROP COLUMN IF EXISTS fts;',
        r.tablename
      );
      EXECUTE format(
        'DROP INDEX IF EXISTS %I;',
        r.tablename || ''_fts_idx''
      );
    END LOOP;
  END $$;
  ```

Make sure Elasticsearch is configured and healthy before removing Postgres FTS if you
rely on lexical search in production.
