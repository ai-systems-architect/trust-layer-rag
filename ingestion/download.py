import hashlib
import logging
import os
import subprocess

import boto3
import requests
from pathlib import Path

from config import (
    S3_BUCKET,
    S3_RAW_PREFIX,
    LOCAL_RAW_DIR as _RAW_DIR,
    NIST_800_53_URL,
    NIST_AI_RMF_URL,
    NIST_AI_600_1_URL,
    FEDRAMP_MODERATE_URL,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCAL_RAW_DIR = Path(_RAW_DIR)

# Add new corpus source here — no other file needs to change
SOURCES = {
    "nist_800_53":               (NIST_800_53_URL,      "nist_800_53.pdf"),
    "nist_ai_rmf":               (NIST_AI_RMF_URL,      "nist_ai_rmf.pdf"),
    "nist_ai_600_1":             (NIST_AI_600_1_URL,    "nist_ai_600_1.pdf"),
    "fedramp_moderate_baseline": (FEDRAMP_MODERATE_URL, "fedramp_moderate_baseline.docx"),
}


def download_file(url: str, dest: Path) -> str:
    """Download url to dest, return SHA-256 checksum. Skips if file exists."""
    if dest.exists():
        logger.info("Already exists, skipping download: %s", dest.name)
        return _checksum(dest)

    logger.info("Downloading %s", url)
    response = requests.get(url, timeout=60, stream=True)
    response.raise_for_status()

    dest.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()

    # stream in chunks — avoids loading full PDF into memory
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            sha256.update(chunk)  # checksum computed in-flight, no second pass

    checksum = sha256.hexdigest()
    logger.info("Saved %s — SHA-256: %s", dest.name, checksum)
    return checksum


def convert_docx_to_pdf(docx_path: Path) -> Path:
    """Convert .docx to PDF via LibreOffice headless.
    Preserves table structure — avoids python-docx cell extraction noise.
    See docs/decision_log.md DL-011."""
    pdf_path = docx_path.with_suffix(".pdf")
    if pdf_path.exists():
        logger.info("Already converted, skipping: %s", pdf_path.name)
        return pdf_path

    # Mac: Homebrew installs as 'soffice'. Linux/EC2/Docker: 'libreoffice'.
    # LIBREOFFICE_CMD env var overrides — default covers both platforms.
    import shutil
    lo_cmd = os.getenv("LIBREOFFICE_CMD") or (
        "soffice" if shutil.which("soffice") else "libreoffice"
    )
    logger.info("Converting %s to PDF via LibreOffice (%s)", docx_path.name, lo_cmd)
    subprocess.run(
        [lo_cmd, "--headless", "--convert-to", "pdf",
         "--outdir", str(docx_path.parent), str(docx_path)],
        check=True
    )
    logger.info("Converted: %s", pdf_path.name)
    return pdf_path


def upload_to_s3(local_path: Path, s3_key: str) -> None:
    """Upload file to S3 raw prefix."""
    s3 = boto3.client("s3")
    logger.info("Uploading %s to s3://%s/%s", local_path.name, S3_BUCKET, s3_key)
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def _checksum(path: Path) -> str:
    """Compute SHA-256 of an existing file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def download_corpus() -> dict:
    """Download all corpus sources. Converts FedRAMP .docx to PDF.
    Returns checksum map keyed by source name."""
    checksums = {}

    for source_key, (url, filename) in SOURCES.items():
        local_path = LOCAL_RAW_DIR / filename
        checksum = download_file(url, local_path)

        # FedRAMP is the only .docx — convert before parse step
        if local_path.suffix == ".docx":
            local_path = convert_docx_to_pdf(local_path)

        checksums[source_key] = checksum

        # skip S3 upload if bucket not configured — allows local-only runs
        if S3_BUCKET:
            upload_to_s3(local_path, f"{S3_RAW_PREFIX}{local_path.name}")

    return checksums


if __name__ == "__main__":
    checksums = download_corpus()
    logger.info("Corpus download complete — %d sources", len(checksums))
    for source, checksum in checksums.items():
        logger.info("  %s: %s", source, checksum)
