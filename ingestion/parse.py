import logging
import re
import fitz  # PyMuPDF
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCAL_RAW_DIR = Path("data/raw")

# Source metadata — display name and version per corpus key
SOURCE_METADATA = {
    "nist_800_53": {
        "display_name": "NIST SP 800-53 Rev 5",
        "version": "Rev 5",
        "date": "2020-09-23",
    },
    "nist_ai_rmf": {
        "display_name": "NIST AI Risk Management Framework 1.0",
        "version": "1.0",
        "date": "2023-01-26",
    },
    "nist_ai_600_1": {
        "display_name": "NIST AI 600-1 GenAI Profile",
        "version": "1.0",
        "date": "2024-07-26",
    },
    "fedramp_moderate_baseline": {
        "display_name": "FedRAMP Moderate Security Controls Baseline",
        "version": "Rev 5",
        "date": "2022-01-04",
    },
}

# Maps source key to PDF filename — FedRAMP uses converted PDF, not original .docx
SOURCE_FILES = {
    "nist_800_53":               "nist_800_53.pdf",
    "nist_ai_rmf":               "nist_ai_rmf.pdf",
    "nist_ai_600_1":             "nist_ai_600_1.pdf",
    "fedramp_moderate_baseline": "fedramp_moderate_baseline.pdf",  # converted by download.py
}


def clean_text(text: str) -> str:
    """Remove common PDF extraction artifacts from government documents."""
    # collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # remove standalone page numbers
    text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
    # rejoin words hyphenated across line breaks
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
    # strip leading/trailing whitespace per line
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


def parse_pdf(source_key: str) -> list[dict]:
    """Extract and clean text from a PDF. Returns list of page-level dicts
    with text and source metadata attached."""
    filename = SOURCE_FILES[source_key]
    pdf_path = LOCAL_RAW_DIR / filename
    metadata = SOURCE_METADATA[source_key]

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path} — run download.py first")

    logger.info("Parsing %s (%s)", filename, metadata["display_name"])
    pages = []

    with fitz.open(str(pdf_path)) as doc:
        for page_num, page in enumerate(doc, start=1):
            raw_text = page.get_text()
            cleaned = clean_text(raw_text)

            # skip near-empty pages — cover pages, blank separators
            if len(cleaned) < 100:
                continue

            pages.append({
                "text": cleaned,
                "source": source_key,
                "display_name": metadata["display_name"],
                "version": metadata["version"],
                "date": metadata["date"],
                "page": page_num,
            })

    logger.info("Parsed %d pages from %s", len(pages), filename)
    return pages


def parse_corpus() -> dict[str, list[dict]]:
    """Parse all corpus sources. Returns dict of source key → page list."""
    corpus = {}
    for source_key in SOURCE_FILES:
        corpus[source_key] = parse_pdf(source_key)
    return corpus


if __name__ == "__main__":
    corpus = parse_corpus()
    for source, pages in corpus.items():
        logger.info("%s: %d pages parsed", source, len(pages))
