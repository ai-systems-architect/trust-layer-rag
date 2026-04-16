import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Optional

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

# ---------------------------------------------------------------------------
# Metadata extraction — control_family and impact_level
# see docs/decision_log.md DL-023
# ---------------------------------------------------------------------------

# NIST 800-53 control family prefixes — uppercase letter groups before the hyphen
# Pattern matches AC-2, AU-12, CM-7, IR-4(1), RA-5, SA-11, SC-28, SI-3 etc.
# Does not match MAP-1.1 or AI RMF subcategory IDs — those use different separators
# and longer prefixes. NIST 800-53 families are all 2–4 uppercase letters.
_CONTROL_ID_RE = re.compile(r'\b([A-Z]{2,4})-\d+')

# Source keys that carry FedRAMP impact level metadata
_FEDRAMP_SOURCES = {"fedramp_moderate_baseline"}

# FedRAMP impact level by source key — extend if High/Low baselines are added
_FEDRAMP_IMPACT = {
    "fedramp_moderate_baseline": "Moderate",
}

# Recognized NIST 800-53 control family prefixes — guards against false positives
# (e.g. "AI-" or "ML-" patterns that are not 800-53 families)
_VALID_800_53_FAMILIES = {
    "AC", "AT", "AU", "CA", "CM", "CP", "IA", "IR", "MA",
    "MP", "PE", "PL", "PM", "PS", "PT", "RA", "SA", "SC",
    "SI", "SR",
}


def extract_control_family(text: str) -> Optional[str]:
    """Extract the dominant NIST 800-53 control family from chunk text.

    Scans for all control ID patterns and returns the most frequently
    occurring family prefix. If a chunk discusses AC-6, AC-7, and AC-8,
    the dominant family is AC. Returns None if no valid 800-53 family found.

    Single-family chunks (e.g. a chunk entirely about AU-2 supplemental
    guidance) return that family directly. Multi-family chunks (rare in
    600-token splits but possible at page boundaries) return the majority.

    Only NIST 800-53 family prefixes are recognized — AI RMF MAP/GOVERN
    subcategory IDs are excluded by the _VALID_800_53_FAMILIES filter."""
    matches = _CONTROL_ID_RE.findall(text)
    valid = [m for m in matches if m in _VALID_800_53_FAMILIES]
    if not valid:
        return None
    # most common family prefix — Counter returns [(family, count), ...]
    return Counter(valid).most_common(1)[0][0]


def extract_impact_level(source_key: str) -> Optional[str]:
    """Return FedRAMP impact level for FedRAMP source chunks, None otherwise.
    Impact level is source-derived, not extracted from text — the corpus
    currently contains only the Moderate baseline. Extend _FEDRAMP_IMPACT
    if Low or High baselines are added."""
    return _FEDRAMP_IMPACT.get(source_key)


def chunk_pages(source_key: str, pages: list[dict]) -> list[dict]:
    """Split parsed pages into overlapping chunks. Metadata from parent
    page attached to every chunk — source, version, date, page number.
    control_family and impact_level extracted per-chunk for metadata filtering.
    see docs/decision_log.md DL-023"""
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
                # metadata columns for SQL pre-filter (DL-023)
                "control_family": extract_control_family(text),
                "impact_level": extract_impact_level(source_key),
            })
    return chunks


def chunk_corpus(corpus: dict) -> list[dict]:
    """Chunk all parsed sources. Returns flat list of all chunk dicts.
    Logs control_family coverage per source — useful for verifying extraction
    quality before re-ingestion commit."""
    all_chunks = []
    for source_key, pages in corpus.items():
        chunks = chunk_pages(source_key, pages)
        families_found = sum(1 for c in chunks if c["control_family"])
        logger.info(
            "%s: %d chunks from %d pages (%d with control_family)",
            source_key, len(chunks), len(pages), families_found,
        )
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
