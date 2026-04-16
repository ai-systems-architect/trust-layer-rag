import logging
from typing import Optional

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


def semantic_search(
    query: str,
    top_k: int = TOP_K_RETRIEVAL,
    source: Optional[str] = None,
    control_family: Optional[str] = None,
    impact_level: Optional[str] = None,
) -> list[dict]:
    """Dense retrieval via pgvector HNSW cosine similarity.

    Optional metadata pre-filters narrow the candidate set before the HNSW
    sweep — callers pass None for any filter they don't need (default behaviour
    is unchanged). Filters are AND-combined when multiple are supplied.

    Args:
        query:          Natural-language query string.
        top_k:          Maximum results to return.
        source:         Restrict to a single corpus source key
                        (e.g. "nist_800_53", "fedramp_moderate_baseline").
        control_family: Restrict to a NIST 800-53 control family prefix
                        (e.g. "AC", "IR", "SC").
        impact_level:   Restrict to a FedRAMP impact level
                        (e.g. "Moderate").

    Returns:
        List of chunk dicts with keys: chunk_id, source, display_name,
        page, chunk_index, text, score, retriever.

    see docs/decision_log.md DL-002, DL-008, DL-023
    """
    vector = embed_query(query)
    conn = get_connection()

    # Build optional WHERE clauses — only include filters that were supplied.
    # Params list mirrors %s placeholders: vector (score), filters..., vector
    # (ORDER BY), top_k (LIMIT).
    where_clauses: list[str] = []
    filter_params: list = []

    if source is not None:
        where_clauses.append("source = %s")
        filter_params.append(source)
    if control_family is not None:
        where_clauses.append("control_family = %s")
        filter_params.append(control_family)
    if impact_level is not None:
        where_clauses.append("impact_level = %s")
        filter_params.append(impact_level)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = f"""
        SELECT
            chunk_id,
            source,
            display_name,
            page,
            chunk_index,
            text,
            1 - (embedding <=> %s::vector) AS score
        FROM chunks
        {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    params = [vector] + filter_params + [vector, top_k]

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
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

    logger.info(
        "semantic_search: %d results | query=%r | source=%s control_family=%s impact_level=%s",
        len(results), query[:60], source, control_family, impact_level,
    )
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
