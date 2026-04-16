import logging
import re

from config import TOP_K_RETRIEVAL, TOP_K_RERANK, LANGFUSE_HOST
from retrieval.semantic import semantic_search
from retrieval.hybrid import hybrid_search
from retrieval.rerank import rerank
from generation.generate import generate, check_guardrail
from tracing.tracer import get_langfuse
from utils.pii_filter import scrub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule-based query classifier — infers metadata pre-filters from query text
# see docs/decision_log.md DL-023
# ---------------------------------------------------------------------------

# Recognised NIST 800-53 control family prefixes — same whitelist as chunk.py.
# Keeping the set co-located with the regex avoids hidden coupling between the
# two files; any new family added to chunk.py should be mirrored here.
_VALID_800_53_FAMILIES = {
    "AC", "AT", "AU", "CA", "CM", "CP", "IA", "IR", "MA",
    "MP", "PE", "PL", "PM", "PS", "PT", "RA", "SA", "SC",
    "SI", "SR",
}

# Matches NIST 800-53 control IDs (AC-2, IR-4, SC-28, AU-12) in query text.
# Uppercase match only — AC-2, not ac-2. Same pattern as chunk.py extraction.
_CONTROL_ID_RE = re.compile(r'\b([A-Z]{2,4})-\d+')

# FedRAMP impact level keyword patterns — extend if Low/High baselines are added.
# Moderate is the only baseline in the current corpus.
_FEDRAMP_MODERATE_RE = re.compile(
    r'\b(fedramp\s+moderate|moderate\s+baseline|fedramp\s+moderate\s+baseline)\b',
    re.IGNORECASE,
)


def classify_query(query: str) -> dict:
    """Infer metadata pre-filters from query text using rule-based patterns.

    Inspects the query for NIST 800-53 control IDs and FedRAMP impact level
    keywords. Returns a dict of filter kwargs to pass directly to
    semantic_search() / hybrid_search(). Any filter that cannot be inferred
    is omitted (None default in the retrieval functions preserves full-corpus
    behaviour).

    Design decision: rule-based over ML classifier — zero latency, fully
    deterministic, auditable. Compliance queries are structured enough that
    explicit control IDs (AC-2, IR-4) and FedRAMP keywords are reliable
    signals. An ML classifier adds complexity without meaningful recall gain
    at this corpus size.
    see docs/decision_log.md DL-023

    Returns:
        Dict with zero or more of: control_family (str), impact_level (str).
        Keys are absent (not None) when no signal is found — callers can
        pass **filters directly as kwargs to retrieval functions.
    """
    filters: dict = {}

    # Extract the first valid 800-53 family found in the query.
    # First match is used — queries rarely span multiple unrelated families,
    # and the most important family typically appears first (e.g. "AC-2 and AU-12"
    # is fundamentally an access-control question).
    for match in _CONTROL_ID_RE.finditer(query):
        family = match.group(1)
        if family in _VALID_800_53_FAMILIES:
            filters["control_family"] = family
            break  # first valid family wins

    # FedRAMP Moderate impact level signal
    if _FEDRAMP_MODERATE_RE.search(query):
        filters["impact_level"] = "Moderate"

    if filters:
        logger.info("classify_query: inferred filters=%s for query=%r", filters, query[:60])

    return filters


def run_pipeline(query: str, use_hybrid: bool = True) -> dict:
    """End-to-end compliance query pipeline with Langfuse tracing.
    input guardrail → classify → retrieve (with metadata pre-filter) → rerank → generate
    Each stage traced as a child span. Input guardrail short-circuits before
    retrieval fires — blocked queries return immediately with no downstream cost.
    use_hybrid=True (default); set False for semantic-only baseline (RAGAs Step 8).
    see docs/decision_log.md DL-008, DL-006, DL-022, DL-023"""

    # --- PII scrub ---
    # Scrub query before any external service call (OpenAI embedding, Cohere rerank,
    # Bedrock). Original query retained for user-facing display only.
    # query_clean is passed to all downstream stages including Langfuse traces.
    # see docs/decision_log.md DL-017
    query_clean = scrub(query)

    # --- input guardrail gate ---
    # Receives scrubbed query — PII stripped before reaching Bedrock trace logs.
    # Blocks prompt injection, off-topic queries, and jailbreak patterns without
    # invoking pgvector, Cohere, or Claude generation.
    guardrail_check = check_guardrail(query_clean, source="INPUT")
    if guardrail_check["blocked"]:
        logger.info("run_pipeline: query blocked by input guardrail")
        return {
            "query": query,
            "retriever": "blocked",
            "chunks": [],
            "answer": (
                "Your query was blocked by the input guardrail. "
                "Please ask a compliance-related question about NIST 800-53, "
                "AI RMF, AI 600-1, or FedRAMP."
            ),
            "model": None,
            "guardrail_action": guardrail_check["action"],
            "trace_id": None,
        }

    # --- metadata filter classification ---
    # Rule-based classifier runs on the scrubbed query — infers control_family
    # and/or impact_level from control IDs and FedRAMP keywords in the query.
    # Filters are passed to retrieval as SQL WHERE clauses; queries with no
    # recognisable signals get a full-corpus scan (filters={}, unchanged behaviour).
    # see docs/decision_log.md DL-023
    filters = classify_query(query_clean)

    lf = get_langfuse()
    trace = lf.trace(
        name="compliance-query",
        # query_clean in trace — scrubbed version logged to Langfuse Cloud
        # filters logged so per-query pre-filter decisions are visible in dashboard
        input={
            "query": query_clean,
            "retriever": "hybrid" if use_hybrid else "semantic",
            "filters": filters,
        },
    )

    try:
        # --- retrieve ---
        span = trace.span(name="retrieve", input={"query": query_clean, "use_hybrid": use_hybrid,
                                                   "filters": filters})
        if use_hybrid:
            chunks = hybrid_search(query_clean, top_k=TOP_K_RETRIEVAL, **filters)
        else:
            chunks = semantic_search(query_clean, top_k=TOP_K_RETRIEVAL, **filters)
        span.end(output={"chunk_count": len(chunks)})

        # --- rerank ---
        span = trace.span(name="rerank", input={"chunk_count": len(chunks)})
        reranked = rerank(query_clean, chunks, top_k=TOP_K_RERANK)
        span.end(output={"chunk_count": len(reranked)})

        # --- generate ---
        span = trace.span(name="generate", input={"chunk_count": len(reranked)})
        result = generate(query_clean, reranked)
        span.end(output={
            "answer_preview": result["answer"][:200],
            "guardrail_action": result["guardrail_action"],
        })

        trace.update(output={"answer": result["answer"]})

    finally:
        lf.flush()

    return {
        "query": query,
        "retriever": "hybrid" if use_hybrid else "semantic",
        # filters dict — control_family / impact_level inferred by classify_query.
        # Empty dict when no signal found (full-corpus retrieval). Surfaced in
        # app.py caption and Langfuse trace input for auditability.
        "filters": filters,
        "chunks": reranked,
        "answer": result["answer"],
        "model": result["model"],
        "guardrail_action": result["guardrail_action"],
        "trace_id": trace.id,
    }


if __name__ == "__main__":
    sample_query = "What controls govern access management in federal systems?"

    print(f"\nQuery: {sample_query}\n")
    print("Running pipeline (hybrid retrieval)...")
    output = run_pipeline(sample_query, use_hybrid=True)

    print(f"\nAnswer:\n{output['answer']}")
    print(f"\nRetriever:        {output['retriever']}")
    print(f"Guardrail action: {output['guardrail_action']}")
    print(f"Trace ID:         {output['trace_id']}")
    print(f"Langfuse:         {LANGFUSE_HOST}")
