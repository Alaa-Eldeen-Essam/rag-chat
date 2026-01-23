import asyncio
import json
import logging
import os
import re
import subprocess
from typing import Any, Dict, List, Optional


class OllamaCliRerankerProvider:
    """
    Reranker provider that shells out to `ollama run <model>`.

    The model is prompted to return JSON only, matching the structure expected
    by the existing reranker integration (list of {index, score} objects).
    """

    def __init__(
        self,
        model_id: str,
        timeout: float = 60.0,
        max_document_chars: int = 2000,
        ollama_host: Optional[str] = None,
    ):
        self.model_id = model_id
        self.timeout = timeout
        self.max_document_chars = max_document_chars
        self.ollama_host = ollama_host
        self.logger = logging.getLogger(__name__)

    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not query or not documents:
            return []

        limit = min(top_n, len(documents)) if top_n else len(documents)
        candidates = documents[:limit]
        prompt = self._build_prompt(query, candidates)

        output = await asyncio.to_thread(self._run_ollama, prompt)
        if not output:
            return []

        payload = self._parse_json(output)
        return self._normalize_results(payload, limit)

    def _build_prompt(self, query: str, documents: List[str]) -> str:
        doc_lines = []
        for idx, text in enumerate(documents):
            cleaned = (text or "").strip()
            if self.max_document_chars > 0 and len(cleaned) > self.max_document_chars:
                cleaned = cleaned[: self.max_document_chars].rstrip()
            doc_lines.append(f"[{idx}] {cleaned}")

        doc_block = "\n".join(doc_lines)
        return (
            "You are a reranker. Given a query and candidate documents, return JSON ONLY.\n"
            "Output schema:\n"
            "{\n"
            '  "results": [\n'
            "    {\"index\": 0, \"score\": 0.95}\n"
            "  ]\n"
            "}\n"
            "Rules:\n"
            "- Include one entry per document.\n"
            "- Indices must match the document list order.\n"
            "- Scores are floats in [0,1], higher means more relevant.\n"
            "- Do not include any extra text.\n\n"
            f"Query:\n{query}\n\n"
            f"Documents:\n{doc_block}\n"
        )

    def _run_ollama(self, prompt: str) -> str:
        cmd = ["ollama", "run", self.model_id, "--format", "json"]
        env = os.environ.copy()
        if self.ollama_host:
            env["OLLAMA_HOST"] = self.ollama_host

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                env=env,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError:
            self.logger.error("ollama CLI not found in PATH")
            return ""
        except subprocess.TimeoutExpired:
            self.logger.error("ollama run timed out after %s seconds", self.timeout)
            return ""
        except Exception as exc:
            self.logger.error("ollama run failed: %s", exc)
            return ""

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            if "unknown flag" in stderr.lower() and "--format" in stderr:
                return self._run_ollama_no_format(prompt, env)
            self.logger.error("ollama run error: %s", stderr or result.stdout)
            return ""

        return (result.stdout or "").strip()

    def _run_ollama_no_format(self, prompt: str, env: Dict[str, str]) -> str:
        cmd = ["ollama", "run", self.model_id]
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                capture_output=True,
                env=env,
                timeout=self.timeout,
                check=False,
            )
        except Exception as exc:
            self.logger.error("ollama run fallback failed: %s", exc)
            return ""

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            self.logger.error("ollama run fallback error: %s", stderr or result.stdout)
            return ""

        return (result.stdout or "").strip()

    def _parse_json(self, output: str) -> Any:
        if not output:
            return None

        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass

        # Try to recover a JSON object/array from mixed output.
        match = re.search(r"(\{.*\}|\[.*\])", output, re.DOTALL)
        if match:
            snippet = match.group(1)
            try:
                return json.loads(snippet)
            except json.JSONDecodeError:
                return None
        return None

    def _normalize_results(self, payload: Any, limit: int) -> List[Dict[str, Any]]:
        if not payload:
            return []

        entries = None
        if isinstance(payload, dict):
            entries = payload.get("results") or payload.get("data") or payload.get("documents")
        elif isinstance(payload, list):
            entries = payload

        if not isinstance(entries, list):
            self.logger.warning("Unexpected ollama reranker payload: %s", payload)
            return []

        normalized: List[Dict[str, Any]] = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            score = item.get("score")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                continue
            if idx_int < 0 or idx_int >= limit:
                continue
            try:
                score_val = float(score) if score is not None else 0.0
            except (TypeError, ValueError):
                score_val = 0.0
            normalized.append({"index": idx_int, "score": score_val})

        return normalized
