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


def drop_table(conn) -> None:
    """Drop chunks table and all dependent indexes.
    Required when adding new columns — CREATE TABLE IF NOT EXISTS is a no-op
    on an existing table, so schema changes require drop + recreate.
    Called explicitly before create_table() during re-ingestion runs.
    see docs/decision_log.md DL-023"""
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS chunks CASCADE;")
    conn.commit()
    logger.info("chunks table dropped (CASCADE removes indexes)")


def create_table(conn) -> None:
    """Create chunks table with metadata columns for filtered retrieval.

    Metadata columns added for Enhancement 14 (DL-023):
      control_family TEXT — NIST control family prefix (AC, AU, CM, IR, SC, SI, RA, SA…)
                            Extracted from chunk text at ingestion. NULL for non-800-53 sources.
      impact_level   TEXT — FedRAMP impact applicability (Low / Moderate / High).
                            NULL for non-FedRAMP sources. 'Moderate' for all FedRAMP chunks
                            in the current corpus (FedRAMP Moderate Baseline only).

    Both columns are nullable — metadata is source-specific, never fabricated.
    chunk_id UNIQUE — prevents duplicate ingestion on re-run.
    see docs/decision_log.md DL-023"""
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS chunks (
                id             SERIAL PRIMARY KEY,
                chunk_id       TEXT UNIQUE NOT NULL,
                source         TEXT NOT NULL,
                display_name   TEXT NOT NULL,
                version        TEXT,
                date           TEXT,
                page           INTEGER,
                chunk_index    INTEGER,
                text           TEXT NOT NULL,
                control_family TEXT,
                impact_level   TEXT,
                embedding      vector({EMBEDDING_DIMENSIONS})
            );
        """)
    conn.commit()
    logger.info("chunks table ready (with control_family, impact_level columns)")


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
    see docs/decision_log.md DL-008"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chunks_text_fts
            ON chunks
            USING gin(to_tsvector('english', text));
        """)
    conn.commit()
    logger.info("tsvector GIN index created")


def create_source_index(conn) -> None:
    """B-tree index on source column — supports WHERE source = %s pre-filter
    in metadata-aware retrieval. B-tree is appropriate for low-cardinality
    equality filters (4 distinct source values). Not HNSW — no vector ops here.
    see docs/decision_log.md DL-023"""
    with conn.cursor() as cur:
        cur.execute("""
            CREATE INDEX IF NOT EXISTS chunks_source_idx
            ON chunks (source);
        """)
    conn.commit()
    logger.info("source B-tree index created")


def run_setup() -> None:
    """Run full DB setup — safe to re-run, all statements use IF NOT EXISTS.
    Does NOT drop the table — call drop_table() explicitly before re-ingestion."""
    logger.info("Connecting to RDS: %s:%s/%s", RDS_ENDPOINT, RDS_PORT, RDS_DB_NAME)
    conn = get_connection()

    try:
        enable_pgvector(conn)
        create_table(conn)
        create_hnsw_index(conn)
        create_tsvector_index(conn)
        create_source_index(conn)
        logger.info("DB setup complete")
    finally:
        conn.close()


def run_fresh_setup() -> None:
    """Drop and recreate the chunks table — use when schema changes require re-ingestion.
    Destroys all existing chunk data. Run ingest.py + embed.py afterwards."""
    logger.info("Fresh setup — dropping existing table before recreate")
    conn = get_connection()
    try:
        enable_pgvector(conn)
        drop_table(conn)
        create_table(conn)
        create_hnsw_index(conn)
        create_tsvector_index(conn)
        create_source_index(conn)
        logger.info("Fresh DB setup complete — ready for re-ingestion")
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    if "--fresh" in sys.argv:
        run_fresh_setup()
    else:
        run_setup()
