## Retrieval Pipeline Overview

Mini RAG now combines **dense embeddings**, **lexical/BM25 scoring**, and the existing
**metadata filters** before sending evidence to the LLM. The flow for every query is:

1. **Dense semantic search** (pgvector) – top‑k chunks by cosine similarity.
2. **Lexical search** (Postgres full‑text, BM25‑like) – top‑k chunks by exact term match.
3. **Hybrid fusion** – chunk scores are normalized per method and merged with a weighted
   sum (default: 0.6 dense / 0.4 lexical). Chunks that appear in either list participate.
4. **Metadata filtering** – the fused list is filtered by `doc_type`, explicit file filters,
   and any keyword filters already supported by `NLPController`.
5. **LLM prompt assembly** – the best chunks (default `EVIDENCE_DOC_LIMIT`) feed the
   template-specific system/user prompts.

### Dense retrieval

- Stored in `collection_<dim>_<project>` tables (pgvector).  
- Search performed via `search_by_vector` using cosine similarity or dot‑product.
- Results now carry the originating `chunk_id` inside `metadata` so they can be merged
  with lexical hits.

### Lexical retrieval

- Each collection table now contains a generated `fts` column:

  ```sql
  ALTER TABLE collection_x_y
    ADD COLUMN fts tsvector
    GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED;
  CREATE INDEX collection_x_y_fts_idx ON collection_x_y USING GIN (fts);
  ```

- Queries run through `plainto_tsquery` which gives BM25‑like ranking via `ts_rank_cd`.

### Hybrid fusion

- Implemented in `NLPController._fuse_dense_and_lexical_results`.
- Dense/lexical scores are normalized to `[0,1]` separately and combined:

  ```python
  fused_score = 0.6 * dense_norm + 0.4 * lexical_norm
  ```

- Adjust the ratio inside `_fuse_dense_and_lexical_results` if you want lexical matches
  to carry more/less weight.

### Metadata filters

- Existing filters (doc type, asset IDs, keyword constraints) run on the fused list,
  so hybrid retrieval still respects the UI scope and visibility restrictions.
- Each chunk’s metadata now also carries a `page_number` (populated during chunking),
  making it easy to surface page references alongside the retrieved excerpt.

---

## Enabling Lexical Search on Existing Deployments

1. **Run the schema patch for every collection table** (once).  
   The `create_collection` routine now ensures the column/index for new tables, but you
   must run the following block once to retrofit existing tables:

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
         'ALTER TABLE %I
            ADD COLUMN IF NOT EXISTS fts tsvector
            GENERATED ALWAYS AS (to_tsvector(''simple'', coalesce(text, ''''))) STORED;',
         r.tablename
       );
       EXECUTE format(
         'CREATE INDEX IF NOT EXISTS %I ON %I USING GIN (fts);',
         r.tablename || '_fts_idx',
         r.tablename
       );
     END LOOP;
   END $$;
   ```

2. **Restart the API service** after running the migration so the new code path is used.

3. **(Optional) Tune weights** by editing `_fuse_dense_and_lexical_results` if you want
   lexical matches to dominate for term-heavy queries.

4. **Re-indexing is not required** unless you want to rebuild the vector indexes.

---

## Accuracy Expectations

Hybrid retrieval typically improves factual and keyword-heavy questions by 5–15 points in
recall@k/nDCG compared to dense-only search, while keeping paraphrase coverage via dense
embeddings. Keep collecting feedback via the “Helpful / Not helpful” buttons to validate
the gain on your own corpus.
