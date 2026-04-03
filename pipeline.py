import logging

from config import TOP_K_RETRIEVAL, TOP_K_RERANK
from retrieval.semantic import semantic_search
from retrieval.hybrid import hybrid_search
from retrieval.rerank import rerank
from generation.generate import generate
from tracing.tracer import get_langfuse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_pipeline(query: str, use_hybrid: bool = True) -> dict:
    """End-to-end compliance query pipeline with Langfuse tracing.
    retrieve → rerank → generate — each stage traced as a child span.
    use_hybrid=True (default); set False for semantic-only baseline (RAGAs Step 8).
    see docs/decision_log.md DL-008, DL-006"""
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
    print(f"Langfuse:         http://localhost:3000")
