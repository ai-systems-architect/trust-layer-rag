import logging

import psycopg2

from config import (
    RDS_ENDPOINT,
    RDS_PORT,
    RDS_DB_NAME,
    RDS_USER,
    RDS_PASSWORD,
    TOP_K_RETRIEVAL,
)
from retrieval.semantic import embed_query, get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# RRF constant — k=60 is standard; dampens impact of very high ranks
# see docs/decision_log.md DL-008
RRF_K = 60


def dense_search(conn, vector: list[float], top_k: int) -> list[dict]:
    """pgvector HNSW cosine search — dense retrieval leg."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chunk_id, source, display_name, page, chunk_index, text
            FROM chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
            """,
            (vector, top_k),
        )
        rows = cur.fetchall()
    return [
        {
            "chunk_id": row[0],
            "source": row[1],
            "display_name": row[2],
            "page": row[3],
            "chunk_index": row[4],
            "text": row[5],
        }
        for row in rows
    ]


def sparse_search(conn, query: str, top_k: int) -> list[dict]:
    """tsvector GIN BM25-style keyword search — sparse retrieval leg.
    plainto_tsquery handles multi-word phrases and strips stop words safely.
    websearch_to_tsquery is more expressive but plainto_tsquery is robust
    for unstructured compliance queries.
    see docs/decision_log.md DL-008"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT chunk_id, source, display_name, page, chunk_index, text
            FROM chunks
            WHERE to_tsvector('english', text) @@ plainto_tsquery('english', %s)
            ORDER BY ts_rank(
                to_tsvector('english', text),
                plainto_tsquery('english', %s)
            ) DESC
            LIMIT %s;
            """,
            (query, query, top_k),
        )
        rows = cur.fetchall()
    return [
        {
            "chunk_id": row[0],
            "source": row[1],
            "display_name": row[2],
            "page": row[3],
            "chunk_index": row[4],
            "text": row[5],
        }
        for row in rows
    ]


def reciprocal_rank_fusion(
    dense_results: list[dict],
    sparse_results: list[dict],
    k: int = RRF_K,
) -> list[dict]:
    """Merge dense and sparse rank lists via RRF.
    RRF score = 1/(k + rank_dense) + 1/(k + rank_sparse)
    Chunks appearing in both lists score higher — natural precision boost.
    see docs/decision_log.md DL-008"""
    scores: dict[str, float] = {}
    chunks: dict[str, dict] = {}

    for rank, result in enumerate(dense_results, start=1):
        cid = result["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        chunks[cid] = result

    for rank, result in enumerate(sparse_results, start=1):
        cid = result["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        chunks[cid] = result

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {**chunks[cid], "score": round(score, 6), "retriever": "hybrid"}
        for cid, score in ranked
    ]


def hybrid_search(query: str, top_k: int = TOP_K_RETRIEVAL) -> list[dict]:
    """Hybrid retrieval: dense (pgvector) + sparse (tsvector) fused via RRF.
    Both legs retrieve top_k independently; RRF merges and re-ranks.
    see docs/decision_log.md DL-008"""
    vector = embed_query(query)
    conn = get_connection()

    try:
        dense = dense_search(conn, vector, top_k)
        sparse = sparse_search(conn, query, top_k)
    finally:
        conn.close()

    logger.info(
        "hybrid_search: dense=%d sparse=%d for query=%r",
        len(dense), len(sparse), query[:60],
    )

    results = reciprocal_rank_fusion(dense, sparse)
    return results[:top_k]


if __name__ == "__main__":
    # smoke test — compare hybrid vs semantic side by side
    from retrieval.semantic import semantic_search

    sample_query = "What controls govern access management in federal systems?"

    print(f"\nQuery: {sample_query}\n")
    print("=" * 60)
    print("HYBRID (dense + sparse + RRF)")
    print("=" * 60)
    for i, r in enumerate(hybrid_search(sample_query, top_k=5), 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()

    print("=" * 60)
    print("SEMANTIC ONLY (dense)")
    print("=" * 60)
    for i, r in enumerate(semantic_search(sample_query, top_k=5), 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()
