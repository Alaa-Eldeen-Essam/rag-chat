from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time

# Define metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP Request Latency', ['method', 'endpoint'])
PROMPT_GUARD_BYPASS_TOTAL = Counter(
    "prompt_guard_bypass_total",
    "Prompt guard bypass header attempts by allow decision",
    ["allowed"],
)
RAG_FALLBACK_TOTAL = Counter(
    "rag_fallback_total",
    "RAG fallback answers emitted",
    ["mode"],
)
RAG_CLARIFICATION_TOTAL = Counter(
    "rag_clarification_total",
    "RAG clarification responses emitted",
    ["mode"],
)
MULTIHOP_SCOPE_PROJECTS = Histogram(
    "multihop_scope_projects",
    "Number of projects included in multihop retrieval scope",
)

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):

        start_time = time.time()

        # Process the request
        response = await call_next(request)

        # Record metrics after request is processed
        duration = time.time() - start_time
        endpoint = request.url.path

        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(duration)
        REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status=response.status_code).inc()

        return response

def setup_metrics(app: FastAPI):
    """
    Setup Prometheus metrics middleware and endpoint
    """
    # Add Prometheus middleware
    app.add_middleware(PrometheusMiddleware)

    @app.get("/TrhBVe_m5gg2002_E5VVqS", include_in_schema=False)
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
