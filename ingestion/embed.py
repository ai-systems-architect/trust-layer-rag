import json
import logging
import time
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values
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
    CHUNKS_PATH as _CHUNKS_PATH,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path(_CHUNKS_PATH)

BATCH_SIZE = 100          # OpenAI embeddings API limit per request
COST_PER_1K_TOKENS = 0.00013  # text-embedding-3-large pricing (USD)


def load_chunks() -> list[dict]:
    """Load chunks.json — written by chunk.py."""
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Chunks file not found: {CHUNKS_PATH} — run ingest.py first")
    with open(CHUNKS_PATH) as f:
        chunks = json.load(f)
    logger.info("Loaded %d chunks from %s", len(chunks), CHUNKS_PATH)
    return chunks


def get_connection():
    """Return psycopg2 connection with SSL enforced — matches rds.force_ssl=1."""
    return psycopg2.connect(
        host=RDS_ENDPOINT,
        port=RDS_PORT,
        dbname=RDS_DB_NAME,
        user=RDS_USER,
        password=RDS_PASSWORD,
        sslmode="require",
    )


def get_existing_chunk_ids(conn) -> set:
    """Return set of chunk_ids already in DB — skip on re-run."""
    with conn.cursor() as cur:
        cur.execute("SELECT chunk_id FROM chunks;")
        return {row[0] for row in cur.fetchall()}


def embed_batch(client: OpenAI, texts: list[str]) -> tuple[list[list[float]], int]:
    """Call OpenAI embeddings API for one batch. Returns (vectors, token_count)."""
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        dimensions=EMBEDDING_DIMENSIONS,
    )
    vectors = [item.embedding for item in response.data]
    tokens = response.usage.total_tokens
    return vectors, tokens


def insert_batch(conn, batch: list[dict], embeddings: list[list[float]]) -> None:
    """Upsert chunk rows — ON CONFLICT (chunk_id) DO NOTHING skips duplicates."""
    rows = [
        (
            chunk["chunk_id"],
            chunk["source"],
            chunk["display_name"],
            chunk.get("version"),
            chunk.get("date"),
            chunk.get("page"),
            chunk.get("chunk_index"),
            chunk["text"],
            embedding,
        )
        for chunk, embedding in zip(batch, embeddings)
    ]
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO chunks
                (chunk_id, source, display_name, version, date, page, chunk_index, text, embedding)
            VALUES %s
            ON CONFLICT (chunk_id) DO NOTHING;
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)",
        )
    conn.commit()


def embed_corpus() -> None:
    """Embed all pending chunks and write to RDS.
    Skips chunks already in DB — safe to re-run after partial failure."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    conn = get_connection()

    try:
        chunks = load_chunks()
        existing = get_existing_chunk_ids(conn)
        pending = [c for c in chunks if c["chunk_id"] not in existing]
        logger.info("%d chunks pending (%d already embedded)", len(pending), len(existing))

        if not pending:
            logger.info("Nothing to embed — all chunks already in DB")
            return

        total_tokens = 0
        total_cost = 0.0

        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i:i + BATCH_SIZE]
            texts = [c["text"] for c in batch]

            vectors, tokens = embed_batch(client, texts)
            insert_batch(conn, batch, vectors)

            total_tokens += tokens
            batch_cost = (tokens / 1000) * COST_PER_1K_TOKENS
            total_cost += batch_cost

            logger.info(
                "Batch %d/%d — %d chunks, %d tokens, $%.4f (running total: $%.4f)",
                i // BATCH_SIZE + 1,
                -(-len(pending) // BATCH_SIZE),  # ceiling division
                len(batch),
                tokens,
                batch_cost,
                total_cost,
            )

            # brief pause — avoids rate limit on large corpora
            if i + BATCH_SIZE < len(pending):
                time.sleep(0.5)

        logger.info(
            "Embedding complete — %d chunks, %d tokens, total cost $%.4f",
            len(pending), total_tokens, total_cost,
        )

    finally:
        conn.close()


if __name__ == "__main__":
    embed_corpus()
