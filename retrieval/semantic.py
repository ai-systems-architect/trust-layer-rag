import logging

import psycopg2
from openai import OpenAI

from config import (
    OPENAI_API_KEY,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    RDS_ENDPOINT,
    RDS_PORT,
    RDS_DB_NAME,
    RDS_USER,
    RDS_PASSWORD,
    TOP_K_RETRIEVAL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def get_connection():
    """SSL-enforced connection — matches rds.force_ssl=1."""
    return psycopg2.connect(
        host=RDS_ENDPOINT,
        port=RDS_PORT,
        dbname=RDS_DB_NAME,
        user=RDS_USER,
        password=RDS_PASSWORD,
        sslmode="require",
    )


def embed_query(query: str) -> list[float]:
    """Embed query with same model used at ingest time — cosine space alignment.
    see docs/decision_log.md DL-003"""
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    return response.data[0].embedding


def semantic_search(query: str, top_k: int = TOP_K_RETRIEVAL) -> list[dict]:
    """Dense retrieval via pgvector HNSW cosine similarity.
    <=> is cosine distance — 1 - distance converts to similarity score.
    see docs/decision_log.md DL-002, DL-008"""
    vector = embed_query(query)
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    chunk_id,
                    source,
                    display_name,
                    page,
                    chunk_index,
                    text,
                    1 - (embedding <=> %s::vector) AS score
                FROM chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
                """,
                (vector, vector, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    results = [
        {
            "chunk_id": row[0],
            "source": row[1],
            "display_name": row[2],
            "page": row[3],
            "chunk_index": row[4],
            "text": row[5],
            "score": round(float(row[6]), 4),
            "retriever": "semantic",
        }
        for row in rows
    ]

    logger.info("semantic_search: %d results for query=%r", len(results), query[:60])
    return results


if __name__ == "__main__":
    # smoke test — run after db/setup.py and ingestion/embed.py
    sample_query = "What controls govern access management in federal systems?"
    results = semantic_search(sample_query, top_k=5)

    print(f"\nQuery: {sample_query}\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()
