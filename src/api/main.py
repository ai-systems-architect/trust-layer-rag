"""
Trust Layer RAG — Retrieval API
Exposes the governed compliance retrieval pipeline as a REST endpoint
for P3 integration. Retrieval + rerank only — no generation.

Usage:
    PYTHONPATH=. uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
    or: ./run_api.sh
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from retrieval.hybrid import hybrid_search
from retrieval.rerank import rerank
from utils.pii_filter import scrub

app = FastAPI(
    title="Trust Layer RAG — Retrieval API",
    description=(
        "Governed compliance RAG retrieval pipeline. "
        "Returns reranked chunks with evidence hashes for P3 integration. "
        "PII scrubbing active on all queries."
    ),
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Framework name ↔ DB source key mapping
# ---------------------------------------------------------------------------

_FRAMEWORK_TO_SOURCE: dict[str, str] = {
    "NIST-800-53": "nist_800_53",
    "AI-RMF":      "nist_ai_rmf",
    "AI-600-1":    "nist_ai_600_1",
    "FedRAMP-Moderate": "fedramp_moderate_baseline",
}

_SOURCE_TO_FRAMEWORK: dict[str, str] = {v: k for k, v in _FRAMEWORK_TO_SOURCE.items()}

# Control ID pattern — same as pipeline.py classify_query
_CONTROL_ID_RE = re.compile(r'\b([A-Z]{2,4}-\d+(?:\(\d+\))?)\b')


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class RetrieveRequest(BaseModel):
    query: str = Field(..., description="The compliance question to retrieve chunks for")
    control_family: Optional[str] = Field(
        default=None,
        description="NIST 800-53 control family prefix — e.g. 'AC', 'IR', 'SC'",
    )
    framework: Optional[str] = Field(
        default=None,
        description=(
            "Restrict retrieval to one corpus source. "
            "Valid values: NIST-800-53, AI-RMF, AI-600-1, FedRAMP-Moderate"
        ),
    )
    top_k: int = Field(default=5, ge=1, le=20, description="Number of chunks to return")


class ChunkResponse(BaseModel):
    text: str              = Field(..., description="Retrieved chunk content")
    source_uri: str        = Field(..., description="Document source identifier")
    retrieval_timestamp: str = Field(..., description="ISO 8601 timestamp of this retrieval")
    evidence_hash: str     = Field(..., description="SHA-256 of chunk text")
    relevance_score: float = Field(..., description="Cohere cross-encoder relevance score")
    framework: str         = Field(..., description="Framework display name")
    control_id: str        = Field(..., description="First control ID found in chunk text, or empty string")


class RetrieveResponse(BaseModel):
    chunks: list[ChunkResponse]
    query: str   = Field(..., description="Original query (pre-PII-scrub)")
    retrieved_at: str = Field(..., description="ISO 8601 timestamp of the full request")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    """Liveness check."""
    return {"status": "ok"}


@app.post("/retrieve", response_model=RetrieveResponse)
def retrieve(request: RetrieveRequest) -> RetrieveResponse:
    """
    Retrieve and rerank compliance chunks for a query.

    Pipeline: PII scrub → hybrid retrieval (dense + BM25 + RRF) →
              Cohere cross-encoder rerank → return top_k chunks.

    Filters (control_family, framework) are applied as SQL WHERE clauses
    before HNSW search — same metadata pre-filter used by the full pipeline.
    """
    retrieved_at = datetime.now(timezone.utc).isoformat()

    # PII scrub — strip personal data before embedding call and trace logs
    query_clean = scrub(request.query)

    # Build metadata filters for the retrieval layer
    filters: dict = {}
    if request.control_family:
        filters["control_family"] = request.control_family.upper()

    if request.framework:
        source_key = _FRAMEWORK_TO_SOURCE.get(request.framework)
        if source_key is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown framework '{request.framework}'. "
                    f"Valid values: {list(_FRAMEWORK_TO_SOURCE.keys())}"
                ),
            )
        filters["source"] = source_key

    # Retrieve — fetch 2× top_k candidates (min 10) before reranking
    candidate_k = max(request.top_k * 2, 10)
    chunks = hybrid_search(query_clean, top_k=candidate_k, **filters)

    if not chunks:
        return RetrieveResponse(chunks=[], query=request.query, retrieved_at=retrieved_at)

    # Rerank — Cohere cross-encoder scores candidates jointly against query
    reranked = rerank(query_clean, chunks, top_k=request.top_k)

    # Build response — compute evidence hash and extract control ID per chunk
    retrieval_timestamp = datetime.now(timezone.utc).isoformat()
    chunk_responses: list[ChunkResponse] = []

    for chunk in reranked:
        text = chunk.get("text", "")
        source = chunk.get("source", "")

        # Extract first control ID from chunk text (best-effort — empty string if absent)
        match = _CONTROL_ID_RE.search(text)
        control_id = match.group(1) if match else ""

        chunk_responses.append(ChunkResponse(
            text=text,
            source_uri=source,
            retrieval_timestamp=retrieval_timestamp,
            evidence_hash=hashlib.sha256(text.encode()).hexdigest(),
            relevance_score=round(chunk.get("rerank_score", 0.0), 6),
            framework=_SOURCE_TO_FRAMEWORK.get(source, source),
            control_id=control_id,
        ))

    return RetrieveResponse(
        chunks=chunk_responses,
        query=request.query,
        retrieved_at=retrieved_at,
    )
