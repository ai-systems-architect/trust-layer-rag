import logging
import os
import re
import sys
import time
from typing import Optional

from config import TOP_K_RETRIEVAL, TOP_K_RERANK, LANGFUSE_HOST
from retrieval.semantic import semantic_search
from retrieval.hybrid import hybrid_search
from retrieval.rerank import rerank
from retrieval.query_enrichment import enrich_query
from generation.generate import generate, check_guardrail
from tracing.tracer import get_langfuse
from utils.pii_filter import scrub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Debug instrumentation gate — when DEBUG_PIPELINE=true is set in the environment,
# run_pipeline() prints formatted RETRIEVE/RERANK/SUMMARY blocks via helpers in
# evaluation/worked_examples_debug.py. Used by scripts/run_worked_examples.py to
# regenerate the worked-example tables in README.md. Zero cost when unset — the
# bool comparison and four `if _DEBUG:` checks are negligible on the hot path.
# see docs/decision_log.md DL-029
_DEBUG = os.getenv("DEBUG_PIPELINE", "").lower() in ("1", "true", "yes")

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


def run_pipeline(
    query: str,
    use_hybrid: bool = True,
    history: Optional[list] = None,
) -> dict:
    """End-to-end compliance query pipeline with Langfuse tracing.

    Pipeline order:
      PII scrub → input guardrail → query enrichment → classify →
      retrieve (pre-filtered) → rerank → generate → output guardrail

    Each stage traced as a child span. Input guardrail short-circuits before
    retrieval fires — blocked queries return immediately with no downstream cost.

    Args:
        query:      Raw user query string.
        use_hybrid: True (default) = dense + sparse + RRF. False = semantic only.
        history:    Prior conversation messages from Streamlit session state.
                    Used by query enrichment to resolve pronouns and ambiguous
                    references before the embedding call. None = first turn.

    see docs/decision_log.md DL-008, DL-006, DL-022, DL-023, DL-025
    """
    _t0 = time.time() if _DEBUG else None

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
            "enriched_query": query_clean,
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

    # --- query enrichment (retrieval-side conversational memory) ---
    # Resolves pronouns and ambiguous references using recent conversation turns
    # before the embedding call. "How does that relate to least privilege?" becomes
    # "How does AC-6 relate to least privilege in NIST 800-53?" — the retriever
    # embeds a fully specified query rather than an unresolved pronoun.
    #
    # Enrichment is bypassed on: first turn (no history), long queries (8+ words),
    # queries with no ambiguous pronouns. All three bypass conditions are O(1).
    # Enrichment failure never blocks the pipeline — falls back to query_clean.
    #
    # classify_query runs on the enriched query so metadata filters benefit
    # from the resolved content (e.g. "that" → "AC-6" triggers control_family=AC).
    # see docs/decision_log.md DL-025
    enriched_query = enrich_query(query_clean, history)
    query_was_enriched = enriched_query != query_clean

    if _DEBUG:
        from evaluation.worked_examples_debug import print_enrichment_block
        print_enrichment_block(
            query_clean, enriched_query, query_was_enriched,
            guardrail_check["action"],
        )

    # --- metadata filter classification ---
    # Run on enriched query — resolved control IDs and FedRAMP keywords are
    # more reliable classification signals than unresolved pronouns.
    # see docs/decision_log.md DL-023
    filters = classify_query(enriched_query)

    lf = get_langfuse()
    trace = lf.trace(
        name="compliance-query",
        # both original and enriched query in trace — Langfuse shows the rewrite
        # quality for every request; "that" → "AC-6" visible in trace input
        input={
            "original_query": query_clean,
            "enriched_query": enriched_query,
            "query_enriched": query_was_enriched,
            "history_turns_used": len((history or [])[-6:]) // 2,
            "retriever": "hybrid" if use_hybrid else "semantic",
            "filters": filters,
        },
    )

    try:
        # --- retrieve ---
        span = trace.span(name="retrieve", input={
            "enriched_query": enriched_query,
            "use_hybrid": use_hybrid,
            "filters": filters,
        })
        if use_hybrid:
            chunks = hybrid_search(enriched_query, top_k=TOP_K_RETRIEVAL, **filters)
        else:
            chunks = semantic_search(enriched_query, top_k=TOP_K_RETRIEVAL, **filters)
        span.end(output={"chunk_count": len(chunks)})

        if _DEBUG:
            from evaluation.worked_examples_debug import print_retrieve_block
            print_retrieve_block(chunks, filters)

        # --- rerank ---
        # Enriched query passed to Cohere — cross-encoder scores against resolved
        # query produce better precision than scoring against an ambiguous pronoun.
        span = trace.span(name="rerank", input={"chunk_count": len(chunks)})
        reranked = rerank(enriched_query, chunks, top_k=TOP_K_RERANK)
        span.end(output={"chunk_count": len(reranked)})

        if _DEBUG:
            from evaluation.worked_examples_debug import print_rerank_block
            print_rerank_block(reranked)

        # --- generate ---
        # Enriched query passed to generation — prompt reflects the resolved intent.
        span = trace.span(name="generate", input={"chunk_count": len(reranked)})
        result = generate(enriched_query, reranked)
        span.end(output={
            "answer_preview": result["answer"][:200],
            "guardrail_action": result["guardrail_action"],
        })

        trace.update(output={"answer": result["answer"]})

        if _DEBUG:
            from evaluation.worked_examples_debug import print_summary_block
            print_summary_block(
                filters, query_was_enriched, guardrail_check["action"],
                result["guardrail_action"], trace.id,
                int((time.time() - _t0) * 1000), result["answer"],
            )

    finally:
        lf.flush()

    return {
        "query": query,
        # enriched_query surfaced in app.py — shown to user when rewrite fired
        # so they can see that "that" was resolved to "AC-6" before retrieval
        "enriched_query": enriched_query,
        "query_was_enriched": query_was_enriched,
        "retriever": "hybrid" if use_hybrid else "semantic",
        # filters derived from enriched query — may capture control IDs that
        # were absent from the raw pronoun query
        "filters": filters,
        "chunks": reranked,
        "answer": result["answer"],
        "model": result["model"],
        "guardrail_action": result["guardrail_action"],
        "trace_id": trace.id,
    }


if __name__ == "__main__":
    _default = "What does AC-6 require and what are its key enhancements?"
    sample_query = sys.argv[1] if len(sys.argv) > 1 else _default

    print(f"\nQuery: {sample_query}\n")
    print("Running pipeline (hybrid retrieval)...")
    output = run_pipeline(sample_query, use_hybrid=True)

    print(f"\nAnswer:\n{output['answer']}")
    print(f"\nRetriever:        {output['retriever']}")
    print(f"Guardrail action: {output['guardrail_action']}")
    print(f"Trace ID:         {output['trace_id']}")
    print(f"Langfuse:         {LANGFUSE_HOST}")
