"""PII filtering — Presidio-based scrubbing for query input and generated output.

Scrubs PII from text before it reaches external services (OpenAI embedding,
Cohere reranking, Langfuse Cloud traces). Runs locally in-process — query text
never leaves the Python environment unscanned.

Integration points (see pipeline.py and generation/generate.py):
1. Query input  — scrub before guardrail and retrieval (most critical: before OpenAI)
2. Generated output — scrub before returning to pipeline (catches query PII echoed in answer)

Langfuse traces receive scrubbed content automatically — pipeline.py passes query_clean
and the scrubbed answer to all trace spans; no separate trace scrubbing needed.

Corpus ingestion hook: federal compliance documents contain no PII. The scrub()
function is available at ingestion if the corpus ever expands to include system
descriptions or assessment reports with real names or identifiers.

Tool selection: Presidio (local, in-process) vs AWS Comprehend (managed AWS API)
- Presidio: query text never leaves Python process before scrubbing; ~10–30ms;
  free; 50+ entity types; correct choice for dev and portfolio.
- AWS Comprehend: stays in AWS boundary; ~100–200ms; $0.0001/query; 16 entity types;
  production choice when fully managed infrastructure is preferred and all services
  are within the same AWS account boundary.

Setup: python -m spacy download en_core_web_lg (required once, ~750MB model)
see docs/decision_log.md DL-017
"""
import logging

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

logger = logging.getLogger(__name__)

# Module-level initialization — AnalyzerEngine loads the spaCy model once at import
# time rather than per call. en_core_web_lg load is ~2–3s; subsequent scrub() calls
# are ~10–30ms. Initializing per-call would add 2–3s latency to every query.
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()

# Entity types scoped to patterns likely in compliance queries.
# Exclusions:
#   LOCATION — compliance queries legitimately reference AWS regions (us-east-1),
#              data center locations, and jurisdiction names — not PII in this context.
#   DATE_TIME — FedRAMP authorization dates, control effective dates, and incident
#              timelines are not PII. Scrubbing these would degrade answer quality.
#   URL       — NIST publication URLs and FedRAMP portal links are corpus citations.
#
# AWS account IDs (12-digit numbers) are not a built-in Presidio entity type.
# Add a custom PatternRecognizer if needed in production deployments.
_ENTITIES = [
    "PERSON",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "US_SSN",
    "US_BANK_NUMBER",
    "CREDIT_CARD",
    "IP_ADDRESS",
    "US_DRIVER_LICENSE",
    "US_PASSPORT",
    "US_ITIN",
    "IBAN_CODE",
    "MEDICAL_LICENSE",
]


def scrub(text: str) -> str:
    """Replace PII entities in text with bracketed type placeholders.
    Returns text unchanged if no PII detected — zero overhead on clean inputs.

    Examples:
        "Does AC-2 apply to john.doe@agency.gov?"
        → "Does AC-2 apply to <EMAIL_ADDRESS>?"

        "Our system at 192.168.1.1 needs FedRAMP auth"
        → "Our system at <IP_ADDRESS> needs FedRAMP auth"

        "Review SSN 123-45-6789 handling under NIST"
        → "Review SSN <US_SSN> handling under NIST"

    Control identifiers (AC-2, IR-4, SC-28, MAP-1.1) are not scrubbed —
    Presidio does not confuse uppercase NIST control IDs with PII patterns.
    Verified: AC-2, IR-4, AU-12, SC-28, CM-7 all pass through unchanged."""
    if not text or not text.strip():
        return text

    results = _analyzer.analyze(text=text, language="en", entities=_ENTITIES)
    if not results:
        return text

    scrubbed = _anonymizer.anonymize(text=text, analyzer_results=results).text
    logger.info(
        "pii_filter.scrub: %d entities detected (len=%d)", len(results), len(text)
    )
    return scrubbed
