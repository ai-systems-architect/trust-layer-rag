import argparse
import logging
import time

from ingestion.download import download_corpus
from ingestion.parse import parse_corpus
from ingestion.chunk import chunk_corpus, save_chunks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run_ingestion(skip_download: bool = False) -> None:
    """Run full ingestion pipeline: download → parse → chunk → save.
    Set skip_download=True to re-run parse/chunk without re-fetching files."""
    start = time.time()

    # step 1 — fetch source documents and stage to S3
    if not skip_download:
        download_corpus()
    else:
        logger.info("Skipping download — using existing files in data/raw/")

    # step 2 — extract and clean text from all four PDFs
    corpus = parse_corpus()

    # step 3 — split into 600-token chunks with metadata
    chunks = chunk_corpus(corpus)

    # step 4 — write to data/processed/chunks.json for embed.py
    save_chunks(chunks)

    elapsed = time.time() - start
    logger.info("Ingestion complete in %.1fs — %d chunks", elapsed, len(chunks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run corpus ingestion pipeline")
    parser.add_argument(
        "--skip-download",
        action="store_true",  # Python internal — flag presence sets True, absence sets False
        help="Skip download step — reuse files already in data/raw/. "
             "Use when iterating on parse/chunk without re-fetching source documents.",
    )
    args = parser.parse_args()
    run_ingestion(skip_download=args.skip_download)
