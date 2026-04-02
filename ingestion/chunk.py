import json
import logging
from pathlib import Path

from langchain.text_splitter import RecursiveCharacterTextSplitter

from config import CHUNK_SIZE, CHUNK_OVERLAP, PROCESSED_DIR as _PROCESSED_DIR
from ingestion.parse import parse_corpus

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROCESSED_DIR = Path(_PROCESSED_DIR)

# initialized once at module level — not re-created per document
splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base",
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
)


def chunk_pages(source_key: str, pages: list[dict]) -> list[dict]:
    """Split parsed pages into overlapping chunks. Metadata from parent
    page attached to every chunk — source, version, date, page number."""
    chunks = []
    for page in pages:
        splits = splitter.split_text(page["text"])
        for idx, text in enumerate(splits):
            chunks.append({
                "text": text,
                "source": source_key,
                "display_name": page["display_name"],
                "version": page["version"],
                "date": page["date"],
                "page": page["page"],
                "chunk_index": idx,
                # unique id — source + page + position within page
                "chunk_id": f"{source_key}_p{page['page']}_c{idx}",
            })
    return chunks


def chunk_corpus(corpus: dict) -> list[dict]:
    """Chunk all parsed sources. Returns flat list of all chunk dicts."""
    all_chunks = []
    for source_key, pages in corpus.items():
        chunks = chunk_pages(source_key, pages)
        logger.info("%s: %d chunks from %d pages", source_key, len(chunks), len(pages))
        all_chunks.extend(chunks)
    logger.info("Total chunks: %d", len(all_chunks))
    return all_chunks


# see docs/decision_log.md DL-012 — why JSON over pickle, parquet, sqlite
def save_chunks(chunks: list[dict]) -> Path:
    """Write chunks to data/processed/chunks.json — input file for embed.py."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / "chunks.json"
    with open(out_path, "w") as f:
        json.dump(chunks, f, indent=2)
    logger.info("Saved %d chunks to %s", len(chunks), out_path)
    return out_path


if __name__ == "__main__":
    corpus = parse_corpus()
    chunks = chunk_corpus(corpus)
    save_chunks(chunks)
