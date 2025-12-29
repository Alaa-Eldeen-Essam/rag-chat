# Benchmarks

## ArabicRAGB (HF datasets)

### Requirements
- Install Python dependencies:
  - `pip install -r src/requirements.txt`

### Probe the dataset
```bash
python scripts/arabic_ragb_probe.py --dataset HeshamHaroon/ArabicRAGB --samples 2
```

### Index cleaned contexts (one-time)
```bash
export RAG_BENCH_AUTH_TOKEN="YOUR_TOKEN"
python scripts/arabic_ragb_eval.py --build-index --doc-type arabic_ragb --max-contexts 0
```

### Run retrieval + generation metrics
```bash
export RAG_BENCH_AUTH_TOKEN="YOUR_TOKEN"
python scripts/arabic_ragb_eval.py --limit 50 --top-k 5 --eval both
```

### Optional environment variables
- `RAG_BENCH_BASE_URL` (default `http://localhost:5000`)
- `RAG_BENCH_PROJECT_ID` (defaults to `/api/v1/users/me` id)
- `RAG_BENCH_AUTH_TOKEN` (Bearer token)
- `RAG_BENCH_BASIC_USER` / `RAG_BENCH_BASIC_PASS` (basic auth)
- `RAG_BENCH_GUARD_HEADER` (default `X-Bypass-Prompt-Guard`)

### Prompt guard bypass
If you want to bypass the prompt guard for evaluation:
```bash
python scripts/arabic_ragb_eval.py --bypass-prompt-guard
```

### Notes on cleaning
The benchmark uses `src/utils/text_cleaning.py` to remove:
- HTML tags/entities and zero-width characters.
- Navigation/boilerplate lines (e.g., "Loading", "تعدى إلى الأعلى").
- Trailing numeric citations like `[1]` or `(1)`.

Cleaning is applied only to the dataset contexts and gold references used
for retrieval evaluation, keeping the user question unchanged.

### Retrieval metrics detail
Retrieval outputs are split into two metric families:
- `overlap_*`: text overlap between retrieved chunks and the full passage text.
- `passage_id_*`: string match using the passage id embedded in the file name.

If you want passage-id matching, pass `--passage-id-key` (e.g. `passage_id`).
The indexer will name files like `arabic_ragb_passage_{id}_*.txt` so that the
retrieval scorer can match by id. If no passage id is available, the id metrics
will stay at 0.0.
