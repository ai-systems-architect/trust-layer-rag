import logging

from config import TOP_K_RETRIEVAL, TOP_K_RERANK, LANGFUSE_HOST
from retrieval.semantic import semantic_search
from retrieval.hybrid import hybrid_search
from retrieval.rerank import rerank
from generation.generate import generate, check_guardrail
from tracing.tracer import get_langfuse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline(query: str, use_hybrid: bool = True) -> dict:
    """End-to-end compliance query pipeline with Langfuse tracing.
    input guardrail → retrieve → rerank → generate → output guardrail
    Each stage traced as a child span. Input guardrail short-circuits before
    retrieval fires — blocked queries return immediately with no downstream cost.
    use_hybrid=True (default); set False for semantic-only baseline (RAGAs Step 8).
    see docs/decision_log.md DL-008, DL-006, DL-022"""

    # --- input guardrail gate ---
    # Runs before retrieval — blocks prompt injection, off-topic queries,
    # and jailbreak patterns without invoking pgvector, Cohere, or Claude.
    # No Langfuse trace created for blocked queries — they are cheap and
    # do not represent pipeline execution worth observing.
    guardrail_check = check_guardrail(query, source="INPUT")
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

    lf = get_langfuse()
    trace = lf.trace(
        name="compliance-query",
        input={"query": query, "retriever": "hybrid" if use_hybrid else "semantic"},
    )

    try:
        # --- retrieve ---
        span = trace.span(name="retrieve", input={"query": query, "use_hybrid": use_hybrid})
        if use_hybrid:
            chunks = hybrid_search(query, top_k=TOP_K_RETRIEVAL)
        else:
            chunks = semantic_search(query, top_k=TOP_K_RETRIEVAL)
        span.end(output={"chunk_count": len(chunks)})

        # --- rerank ---
        span = trace.span(name="rerank", input={"chunk_count": len(chunks)})
        reranked = rerank(query, chunks, top_k=TOP_K_RERANK)
        span.end(output={"chunk_count": len(reranked)})

        # --- generate ---
        span = trace.span(name="generate", input={"chunk_count": len(reranked)})
        result = generate(query, reranked)
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
