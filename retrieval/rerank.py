import logging

import cohere

from config import (
    COHERE_API_KEY,
    RERANK_MODEL,
    TOP_K_RERANK,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def rerank(query: str, chunks: list[dict], top_k: int = TOP_K_RERANK) -> list[dict]:
    """Cross-encoder reranking via Cohere rerank-english-v3.0.
    Bi-encoder (pgvector) similarity has a precision ceiling — cross-encoder
    sees query + chunk together for higher precision on top-K.
    Runs on top-10 chunks only — cost negligible.
    see docs/decision_log.md DL-005"""
    if not chunks:
        return []

    client = cohere.Client(api_key=COHERE_API_KEY)
    documents = [c["text"] for c in chunks]

    response = client.rerank(
        model=RERANK_MODEL,
        query=query,
        documents=documents,
        top_n=top_k,
    )

    results = []
    for hit in response.results:
        chunk = chunks[hit.index].copy()
        chunk["rerank_score"] = round(hit.relevance_score, 6)
        chunk["retriever"] = "reranked"
        results.append(chunk)

    logger.info(
        "rerank: %d → %d chunks for query=%r",
        len(chunks), len(results), query[:60],
    )
    return results


if __name__ == "__main__":
    # smoke test — semantic → hybrid → rerank on same query
    from retrieval.semantic import semantic_search
    from retrieval.hybrid import hybrid_search

    sample_query = "What controls govern access management in federal systems?"

    semantic = semantic_search(sample_query, top_k=10)
    hybrid = hybrid_search(sample_query, top_k=10)
    reranked = rerank(sample_query, hybrid)

    print(f"\nQuery: {sample_query}\n")

    print("=" * 60)
    print("SEMANTIC ONLY (dense, top-5)")
    print("=" * 60)
    for i, r in enumerate(semantic[:5], 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()

    print("=" * 60)
    print("HYBRID (dense + sparse + RRF, top-5)")
    print("=" * 60)
    for i, r in enumerate(hybrid[:5], 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()

    print("=" * 60)
    print("RERANKED (hybrid → Cohere cross-encoder, top-5)")
    print("=" * 60)
    for i, r in enumerate(reranked, 1):
        print(f"[{i}] rerank_score={r['rerank_score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()
