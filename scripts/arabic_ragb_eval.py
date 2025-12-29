import argparse
import base64
import json
import mimetypes
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import request
from urllib.error import HTTPError

from datasets import load_dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.utils.text_cleaning import (  # noqa: E402
    clean_text_for_embeddings,
    normalize_arabic,
)


QUESTION_FIELD_CANDIDATES = [
    "question",
    "query",
    "prompt",
    "instruction",
    "input",
]

CONTEXT_FIELD_CANDIDATES = [
    "context",
    "contexts",
    "passage",
    "passage_text",
    "document",
    "text",
    "article",
]

ANSWER_FIELD_CANDIDATES = [
    "answers",
    "answer",
    "responses",
    "output",
    "target",
]

PASSAGE_ID_FIELD_CANDIDATES = [
    "passage_id",
    "doc_id",
    "document_id",
]

@dataclass
class FieldMapping:
    question_key: str
    context_key: str
    answer_key: Optional[str]
    passage_id_key: Optional[str]


def detect_fields(sample: Dict[str, Any], require_answer: bool = True) -> FieldMapping:
    def pick(candidates: Iterable[str]) -> Optional[str]:
        for candidate in candidates:
            if candidate in sample:
                return candidate
        return None

    question_key = pick(QUESTION_FIELD_CANDIDATES)
    context_key = pick(CONTEXT_FIELD_CANDIDATES)
    answer_key = pick(ANSWER_FIELD_CANDIDATES)
    passage_id_key = pick(PASSAGE_ID_FIELD_CANDIDATES)
    if not question_key or not context_key or (require_answer and not answer_key):
        raise SystemExit(
            "Could not auto-detect question/context/answer fields. "
            f"Available keys: {list(sample.keys())}"
        )
    return FieldMapping(question_key, context_key, answer_key, passage_id_key)


def extract_contexts(row: Dict[str, Any], key: str) -> List[str]:
    context = row.get(key)
    if context is None:
        return []
    if isinstance(context, list):
        return [str(item) for item in context if item]
    return [str(context)]


def extract_answers(row: Dict[str, Any], key: str) -> List[str]:
    answers = row.get(key)
    if answers is None:
        return []
    if isinstance(answers, dict):
        if "text" in answers:
            text = answers.get("text")
            if isinstance(text, list):
                return [str(item) for item in text if item]
            if text:
                return [str(text)]
        return [str(value) for value in answers.values() if value]
    if isinstance(answers, list):
        collected: List[str] = []
        for item in answers:
            if isinstance(item, dict) and "text" in item:
                text = item.get("text")
                if isinstance(text, list):
                    collected.extend([str(val) for val in text if val])
                elif text:
                    collected.append(str(text))
            elif item:
                collected.append(str(item))
        return collected
    return [str(answers)]


def extract_passage_id(row: Dict[str, Any], key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    value = row.get(key)
    if value is None:
        return None
    return str(value).strip()


def normalize_for_overlap(text: str) -> str:
    cleaned = clean_text_for_embeddings(text)
    return normalize_arabic(cleaned)


def token_f1(prediction: str, reference: str) -> float:
    pred_tokens = normalize_arabic(prediction).split()
    ref_tokens = normalize_arabic(reference).split()
    if not pred_tokens or not ref_tokens:
        return 0.0
    pred_set = {}
    for token in pred_tokens:
        pred_set[token] = pred_set.get(token, 0) + 1
    ref_set = {}
    for token in ref_tokens:
        ref_set[token] = ref_set.get(token, 0) + 1
    overlap = 0
    for token, count in pred_set.items():
        if token in ref_set:
            overlap += min(count, ref_set[token])
    precision = overlap / max(1, len(pred_tokens))
    recall = overlap / max(1, len(ref_tokens))
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def exact_match(prediction: str, reference: str) -> float:
    return 1.0 if normalize_arabic(prediction) == normalize_arabic(reference) else 0.0


def build_auth_headers(token: str, basic_user: str, basic_pass: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers
    if basic_user or basic_pass:
        raw = f"{basic_user}:{basic_pass}".encode("utf-8")
        headers["Authorization"] = f"Basic {base64.b64encode(raw).decode('utf-8')}"
    return headers


def render_progress(prefix: str, current: int, total: int) -> None:
    if total <= 0:
        return
    width = 28
    ratio = min(max(current / total, 0), 1)
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    message = f"\r{prefix} [{bar}] {current}/{total}"
    sys.stdout.write(message)
    sys.stdout.flush()
    if current >= total:
        sys.stdout.write("\n")


def http_get_json(url: str, headers: Dict[str, str]) -> Dict[str, Any]:
    req = request.Request(url, headers=headers, method="GET")
    try:
        with request.urlopen(req) as resp:
            payload = resp.read().decode("utf-8")
        return json.loads(payload)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise SystemExit(
            f"HTTP {exc.code} for {url}. "
            "Provide auth via --auth-token or --basic-user/--basic-pass "
            f"(or env RAG_BENCH_AUTH_TOKEN / RAG_BENCH_BASIC_USER/PASS). {detail}"
        ) from exc


def http_post_json(
    url: str, headers: Dict[str, str], payload: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json", **headers}
    req = request.Request(url, data=data, headers=merged, method="POST")
    try:
        with request.urlopen(req) as resp:
            response_data = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(response_data)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise SystemExit(
            f"HTTP {exc.code} for {url}. "
            "Provide auth via --auth-token or --basic-user/--basic-pass "
            f"(or env RAG_BENCH_AUTH_TOKEN / RAG_BENCH_BASIC_USER/PASS). {detail}"
        ) from exc


def encode_multipart(
    fields: List[Tuple[str, str]], files: List[Tuple[str, Path]]
) -> Tuple[str, bytes]:
    boundary = f"----ArabicRAGB{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        body.extend(f"{value}\r\n".encode("utf-8"))
    for field_name, path in files:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{field_name}"; '
                f'filename="{path.name}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
        body.extend(path.read_bytes())
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return boundary, bytes(body)


def http_post_multipart(
    url: str,
    headers: Dict[str, str],
    fields: List[Tuple[str, str]],
    files: List[Tuple[str, Path]],
) -> Tuple[int, Dict[str, Any]]:
    boundary, body = encode_multipart(fields, files)
    merged = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        **headers,
    }
    req = request.Request(url, data=body, headers=merged, method="POST")
    try:
        with request.urlopen(req) as resp:
            response_data = resp.read().decode("utf-8")
            return resp.getcode(), json.loads(response_data)
    except HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = ""
        raise SystemExit(
            f"HTTP {exc.code} for {url}. "
            "Provide auth via --auth-token or --basic-user/--basic-pass "
            f"(or env RAG_BENCH_AUTH_TOKEN / RAG_BENCH_BASIC_USER/PASS). {detail}"
        ) from exc


def resolve_project_id(base_url: str, headers: Dict[str, str], override: Optional[int]) -> int:
    if override:
        return override
    info = http_get_json(f"{base_url}/api/v1/users/me", headers)
    if "id" not in info:
        raise SystemExit("Failed to resolve project id from /api/v1/users/me.")
    return int(info["id"])


def build_index(
    dataset_rows: Iterable[Dict[str, Any]],
    field_map: FieldMapping,
    base_url: str,
    headers: Dict[str, str],
    project_id: int,
    doc_type: str,
    output_dir: Path,
    max_contexts: int,
    batch_size: int,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    seen_hashes = set()
    file_paths: List[Path] = []
    row_total = len(dataset_rows) if hasattr(dataset_rows, "__len__") else 0

    for idx, row in enumerate(dataset_rows):
        if row_total:
            render_progress("Collecting contexts", idx + 1, row_total)
        contexts = extract_contexts(row, field_map.context_key)
        passage_id = extract_passage_id(row, field_map.passage_id_key)
        for ctx in contexts:
            cleaned = clean_text_for_embeddings(str(ctx))
            if not cleaned:
                continue
            ctx_hash = hash(cleaned)
            if ctx_hash in seen_hashes:
                continue
            seen_hashes.add(ctx_hash)
            if passage_id:
                file_name = f"arabic_ragb_passage_{passage_id}_{len(file_paths)}.txt"
            else:
                file_name = f"arabic_ragb_{idx}_{len(file_paths)}.txt"
            file_path = output_dir / file_name
            file_path.write_text(cleaned, encoding="utf-8")
            file_paths.append(file_path)
            if max_contexts and len(file_paths) >= max_contexts:
                break
        if max_contexts and len(file_paths) >= max_contexts:
            break

    if not file_paths:
        return 0

    uploaded = 0
    url = f"{base_url}/api/v1/data/upload/process/index/batch/{project_id}"
    fields = [
        ("chunk_size", "500"),
        ("overlap_size", "100"),
        ("do_reset", "0"),
        ("is_private", "false"),
        ("doc_type", doc_type),
        ("visibility", "global"),
    ]

    total_files = len(file_paths)
    for start in range(0, total_files, batch_size):
        batch = file_paths[start : start + batch_size]
        files = [("files", path) for path in batch]
        status_code, response = http_post_multipart(url, headers, fields, files)
        if status_code >= 400:
            raise SystemExit(f"Upload failed: {response}")
        uploaded += len(batch)
        render_progress("Uploading", uploaded, total_files)
    return uploaded


def compute_retrieval_metrics(
    gold_contexts: List[str],
    sources: List[Dict[str, Any]],
    top_k: int,
    overlap_threshold: float,
) -> Tuple[float, float, float]:
    gold_norm = [normalize_for_overlap(ctx) for ctx in gold_contexts if ctx]
    gold_norm = [ctx for ctx in gold_norm if ctx]
    if not gold_norm:
        return 0.0, 0.0, 0.0

    match_rank = None
    match_count = 0
    for rank, source in enumerate(sources[:top_k], start=1):
        snippet = str(source.get("snippet") or "")
        snippet_norm = normalize_for_overlap(snippet)
        if not snippet_norm:
            continue
        for gold in gold_norm:
            if snippet_norm in gold or gold in snippet_norm:
                match_rank = match_rank or rank
                match_count += 1
                break
            snippet_tokens = set(snippet_norm.split())
            gold_tokens = set(gold.split())
            if not gold_tokens:
                continue
            overlap = len(snippet_tokens & gold_tokens) / max(1, len(gold_tokens))
            if overlap >= overlap_threshold:
                match_rank = match_rank or rank
                match_count += 1
                break

    recall = 1.0 if match_rank is not None else 0.0
    mrr = 1.0 / match_rank if match_rank is not None else 0.0
    precision = match_count / max(1, min(top_k, len(sources)))
    return recall, mrr, precision


def compute_passage_id_metrics(
    expected_passage_id: Optional[str],
    sources: List[Dict[str, Any]],
    top_k: int,
) -> Tuple[float, float, float]:
    if not expected_passage_id:
        return 0.0, 0.0, 0.0
    expected = str(expected_passage_id).strip()
    if not expected:
        return 0.0, 0.0, 0.0

    match_rank = None
    match_count = 0
    for rank, source in enumerate(sources[:top_k], start=1):
        file_name = str(source.get("file_name") or "")
        if expected in file_name:
            match_rank = match_rank or rank
            match_count += 1
    recall = 1.0 if match_rank is not None else 0.0
    mrr = 1.0 / match_rank if match_rank is not None else 0.0
    precision = match_count / max(1, min(top_k, len(sources)))
    return recall, mrr, precision


def compute_generation_metrics(answer: str, references: List[str]) -> Tuple[float, float]:
    if not references:
        return 0.0, 0.0
    em_scores = [exact_match(answer, ref) for ref in references]
    f1_scores = [token_f1(answer, ref) for ref in references]
    return max(em_scores), max(f1_scores)


def run_benchmark(
    dataset_name: str,
    split: str,
    limit: int,
    seed: int,
    base_url: str,
    project_id: Optional[int],
    doc_type: str,
    top_k: int,
    eval_mode: str,
    build_index_flag: bool,
    max_contexts: int,
    batch_size: int,
    overlap_threshold: float,
    bypass_header: Optional[str],
    bypass_value: Optional[str],
    token: str,
    basic_user: str,
    basic_pass: str,
    question_key: Optional[str] = None,
    context_key: Optional[str] = None,
    answer_key: Optional[str] = None,
    passage_id_key: Optional[str] = None,
    include_sample_metrics: bool = False,
) -> Dict[str, Any]:
    headers = build_auth_headers(token, basic_user, basic_pass)
    if bypass_header and bypass_value:
        headers[bypass_header] = bypass_value

    project_id = resolve_project_id(base_url, headers, project_id)

    dataset = load_dataset(dataset_name, split=split)
    if len(dataset) == 0:
        raise SystemExit("Dataset split is empty.")

    sample_row = dataset[0]
    require_answer = eval_mode in {"generation", "both"} and not answer_key
    field_map = detect_fields(sample_row, require_answer=require_answer)
    if question_key:
        field_map.question_key = question_key
    if context_key:
        field_map.context_key = context_key
    if answer_key:
        field_map.answer_key = answer_key
    if passage_id_key:
        field_map.passage_id_key = passage_id_key
    if eval_mode in {"generation", "both"} and not field_map.answer_key:
        raise SystemExit(
            "Generation metrics require an answer field. "
            "Provide --answer-key or run with --eval retrieval."
        )

    if build_index_flag:
        output_dir = ROOT / "data" / "arabic_ragb" / "contexts"
        uploaded = build_index(
            dataset_rows=dataset,
            field_map=field_map,
            base_url=base_url,
            headers=headers,
            project_id=project_id,
            doc_type=doc_type,
            output_dir=output_dir,
            max_contexts=max_contexts,
            batch_size=batch_size,
        )
        print(f"Indexed {uploaded} cleaned contexts.")

    rng = random.Random(seed)
    indices = list(range(len(dataset)))
    rng.shuffle(indices)
    if limit:
        indices = indices[:limit]

    retrieval_scores = []
    retrieval_mrr = []
    retrieval_precision = []
    retrieval_id_scores = []
    retrieval_id_mrr = []
    retrieval_id_precision = []
    generation_em = []
    generation_f1 = []
    skipped = 0
    sample_metrics: Optional[Dict[str, Any]] = None

    total_eval = len(indices)
    for offset, idx in enumerate(indices, start=1):
        render_progress("Evaluating", offset, total_eval)
        row = dataset[idx]
        question = row.get(field_map.question_key)
        if not question:
            skipped += 1
            continue
        contexts = extract_contexts(row, field_map.context_key)
        answers = extract_answers(row, field_map.answer_key) if field_map.answer_key else []
        passage_id = extract_passage_id(row, field_map.passage_id_key)
        if not contexts or (eval_mode in {"generation", "both"} and not answers):
            skipped += 1
            continue

        payload = {
            "text": str(question),
            "limit": top_k,
            "stream": False,
            "doc_type": doc_type,
            "mode": "rag",
        }
        url = f"{base_url}/api/v1/nlp/index/answer/{project_id}"
        status_code, response = http_post_json(url, headers, payload)
        if status_code >= 400:
            print(f"Request failed (idx {idx}): {response}")
            skipped += 1
            continue

        answer_text = str(response.get("answer") or "")
        sources = response.get("sources") or []
        if eval_mode in {"retrieval", "both"}:
            recall, mrr, precision = compute_retrieval_metrics(
                contexts, sources, top_k, overlap_threshold
            )
            retrieval_scores.append(recall)
            retrieval_mrr.append(mrr)
            retrieval_precision.append(precision)
            id_recall, id_mrr, id_precision = compute_passage_id_metrics(
                passage_id, sources, top_k
            )
            retrieval_id_scores.append(id_recall)
            retrieval_id_mrr.append(id_mrr)
            retrieval_id_precision.append(id_precision)
            if include_sample_metrics and sample_metrics is None:
                sample_metrics = {
                    "sample_index": idx,
                    "question": str(question),
                    "passage_id": passage_id,
                    "overlap_recall_at_k": recall,
                    "overlap_mrr_at_k": mrr,
                    "overlap_precision_at_k": precision,
                    "passage_id_recall_at_k": id_recall,
                    "passage_id_mrr_at_k": id_mrr,
                    "passage_id_precision_at_k": id_precision,
                    "top_k": top_k,
                }
        if eval_mode in {"generation", "both"}:
            em, f1 = compute_generation_metrics(answer_text, answers)
            generation_em.append(em)
            generation_f1.append(f1)
            if include_sample_metrics and sample_metrics is None:
                sample_metrics = {
                    "sample_index": idx,
                    "question": str(question),
                    "exact_match": em,
                    "token_f1": f1,
                }

        time.sleep(0.05)

    def avg(values: List[float]) -> float:
        return sum(values) / max(1, len(values))

    results: Dict[str, Any] = {
        "dataset": dataset_name,
        "split": split,
        "doc_type": doc_type,
        "samples": len(indices),
        "skipped": skipped,
        "sample": sample_metrics,
        "retrieval": None,
        "generation": None,
    }
    if eval_mode in {"retrieval", "both"}:
        results["retrieval"] = {
            "overlap_recall_at_k": avg(retrieval_scores),
            "overlap_mrr_at_k": avg(retrieval_mrr),
            "overlap_precision_at_k": avg(retrieval_precision),
            "passage_id_recall_at_k": avg(retrieval_id_scores),
            "passage_id_mrr_at_k": avg(retrieval_id_mrr),
            "passage_id_precision_at_k": avg(retrieval_id_precision),
            "top_k": top_k,
        }
    if eval_mode in {"generation", "both"}:
        results["generation"] = {
            "exact_match": avg(generation_em),
            "token_f1": avg(generation_f1),
        }
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="ArabicRAGB benchmark runner.")
    parser.add_argument("--dataset", default="HeshamHaroon/ArabicRAGB")
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-url", default=os.getenv("RAG_BENCH_BASE_URL", "http://localhost:5000"))
    parser.add_argument("--project-id", type=int, default=os.getenv("RAG_BENCH_PROJECT_ID"))
    parser.add_argument("--doc-type", default="arabic_ragb")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--question-key", default="")
    parser.add_argument("--context-key", default="")
    parser.add_argument("--answer-key", default="")
    parser.add_argument("--passage-id-key", default="")
    parser.add_argument("--sample-metrics", action="store_true")
    parser.add_argument("--auth-token", default="")
    parser.add_argument("--basic-user", default="")
    parser.add_argument("--basic-pass", default="")
    parser.add_argument(
        "--eval",
        choices=["retrieval", "generation", "both"],
        default="both",
    )
    parser.add_argument("--build-index", action="store_true")
    parser.add_argument("--max-contexts", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--overlap-threshold", type=float, default=0.2)
    parser.add_argument("--output", default="")
    parser.add_argument("--bypass-prompt-guard", action="store_true")
    args = parser.parse_args()

    token = args.auth_token or os.getenv("RAG_BENCH_AUTH_TOKEN", "")
    basic_user = args.basic_user or os.getenv("RAG_BENCH_BASIC_USER", "")
    basic_pass = args.basic_pass or os.getenv("RAG_BENCH_BASIC_PASS", "")
    bypass_header = os.getenv("RAG_BENCH_GUARD_HEADER", "X-Bypass-Prompt-Guard")
    bypass_value = "true" if args.bypass_prompt_guard else ""

    project_id = int(args.project_id) if args.project_id is not None else None

    results = run_benchmark(
        dataset_name=args.dataset,
        split=args.split,
        limit=args.limit,
        seed=args.seed,
        base_url=args.base_url,
        project_id=project_id,
        doc_type=args.doc_type,
        top_k=args.top_k,
        eval_mode=args.eval,
        build_index_flag=args.build_index,
        max_contexts=args.max_contexts,
        batch_size=args.batch_size,
        overlap_threshold=args.overlap_threshold,
        bypass_header=bypass_header if args.bypass_prompt_guard else None,
        bypass_value=bypass_value if args.bypass_prompt_guard else None,
        token=token,
        basic_user=basic_user,
        basic_pass=basic_pass,
        question_key=args.question_key or None,
        context_key=args.context_key or None,
        answer_key=args.answer_key or None,
        passage_id_key=args.passage_id_key or None,
        include_sample_metrics=args.sample_metrics,
    )

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
