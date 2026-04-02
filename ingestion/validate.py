import json
import logging
import random
from pathlib import Path
from config import CHUNKS_PATH as _CHUNKS_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path(_CHUNKS_PATH)
REQUIRED_FIELDS = {"text", "source", "display_name", "version", "date", "page",
                   "chunk_index", "chunk_id"}

# Ranges derived from DL-011 chunk estimates with ~35% buffer on each side.
# Wide intentionally — estimates are pre-run. Tighten to ±15% after first
# successful ingest once actual counts are known.
EXPECTED_COUNTS = {
    "nist_800_53":               (2000, 4000),  # estimate ~3,000
    "nist_ai_rmf":               (200,  700),   # estimate ~400
    "nist_ai_600_1":             (100,  600),   # estimate ~300
    "fedramp_moderate_baseline": (700,  2000),  # estimate ~1,200
}


def validate_chunk_counts(chunks: list[dict]) -> None:
    """Assert each source falls within expected chunk count range."""
    counts = {}
    for chunk in chunks:
        counts[chunk["source"]] = counts.get(chunk["source"], 0) + 1

    for source, (low, high) in EXPECTED_COUNTS.items():
        count = counts.get(source, 0)
        if low <= count <= high:
            logger.info("PASS chunk count — %s: %d chunks", source, count)
        else:
            raise ValueError(
                f"FAIL chunk count — {source}: {count} chunks "
                f"(expected {low}–{high})"
            )


def validate_metadata(chunks: list[dict]) -> None:
    """Assert every chunk has all required metadata fields."""
    missing = [
        chunk["chunk_id"]
        for chunk in chunks
        if not REQUIRED_FIELDS.issubset(chunk.keys())
    ]
    if missing:
        raise ValueError(f"FAIL metadata — {len(missing)} chunks missing fields: {missing[:5]}")
    logger.info("PASS metadata — all %d chunks have required fields", len(chunks))


def validate_no_empty_chunks(chunks: list[dict]) -> None:
    """Assert no chunk has empty or whitespace-only text."""
    empty = [chunk["chunk_id"] for chunk in chunks if not chunk.get("text", "").strip()]
    if empty:
        raise ValueError(f"FAIL empty chunks — {len(empty)} empty: {empty[:5]}")
    logger.info("PASS empty check — no empty chunks found")


def sample_chunks(chunks: list[dict]) -> None:
    """Print 2 random chunks per source — visual spot check before embedding."""
    by_source = {}
    for chunk in chunks:
        by_source.setdefault(chunk["source"], []).append(chunk)

    for source, source_chunks in by_source.items():
        logger.info("--- SAMPLE: %s ---", source)
        for chunk in random.sample(source_chunks, min(2, len(source_chunks))):
            logger.info(
                "chunk_id=%s page=%s\n%s\n",
                chunk["chunk_id"], chunk["page"], chunk["text"][:300]
            )


def run_validation() -> None:
    """Load chunks.json and run all validation checks."""
    if not CHUNKS_PATH.exists():
        raise FileNotFoundError(f"Chunks file not found: {CHUNKS_PATH} — run ingest.py first")

    with open(CHUNKS_PATH) as f:
        chunks = json.load(f)

    logger.info("Loaded %d chunks from %s", len(chunks), CHUNKS_PATH)

    validate_chunk_counts(chunks)
    validate_metadata(chunks)
    validate_no_empty_chunks(chunks)
    sample_chunks(chunks)

    logger.info("Validation complete — all checks passed")


if __name__ == "__main__":
    run_validation()
