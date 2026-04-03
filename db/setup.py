import logging
import psycopg2
from config import (
    RDS_ENDPOINT,
    RDS_PORT,
    RDS_DB_NAME,
    RDS_USER,
    RDS_PASSWORD,
    EMBEDDING_DIMENSIONS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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


def enable_pgvector(conn) -> None:
    """Install pgvector extension. Safe to re-run — IF NOT EXISTS."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    logger.info("pgvector extension enabled")


def create_table(conn) -> None:
    """Create chunks table. chunk_id unique — prevents duplicate ingestion."""
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id           SERIAL PRIMARY KEY,
                chunk_id     TEXT UNIQUE NOT NULL,
                source       TEXT NOT NULL,
                display_name TEXT NOT NULL,
                version      TEXT,
                date         TEXT,
                page         INTEGER,
                chunk_index  INTEGER,
                text         TEXT NOT NULL,
                embedding    vector({EMBEDDING_DIMENSIONS})
            );
        """)
    conn.commit()
    logger.info("chunks table ready")


def create_hnsw_index(conn) -> None:
    """Build HNSW index on embedding column for dense retrieval.
    vector_cosine_ops — matches OpenAI embedding similarity metric.
    m=16, ef_construction=64 — pgvector defaults, well-tested at this scale.
    see docs/decision_log.md DL-002"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
            ON chunks
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        """)
    conn.commit()
    logger.info("HNSW index created")


def create_tsvector_index(conn) -> None:
    """Build GIN index on text column for sparse BM25 retrieval.
    Enables exact keyword matching for control identifiers (AC-2, IR-4).
    Activated in Step 4 hybrid retrieval — index created now, used later.
    see docs/decision_log.md DL-008"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chunks_text_fts
            ON chunks
            USING gin(to_tsvector('english', text));
        """)
    conn.commit()
    logger.info("tsvector GIN index created")


def run_setup() -> None:
    """Run full DB setup — safe to re-run, all statements use IF NOT EXISTS."""
    logger.info("Connecting to RDS: %s:%s/%s", RDS_ENDPOINT, RDS_PORT, RDS_DB_NAME)
    conn = get_connection()

    try:
        enable_pgvector(conn)
        create_table(conn)
        create_hnsw_index(conn)
        create_tsvector_index(conn)
        logger.info("DB setup complete")
    finally:
        conn.close()


if __name__ == "__main__":
    run_setup()
