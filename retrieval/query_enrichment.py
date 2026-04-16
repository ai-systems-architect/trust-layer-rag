import logging
from typing import Optional

import boto3

from config import AWS_REGION, GENERATION_MODEL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Query enrichment — retrieval-side conversational memory
# see docs/decision_log.md DL-025
# ---------------------------------------------------------------------------

# Pronouns and demonstratives that signal the query depends on prior context
# to resolve a referent. "How does THAT relate?" → "that" points to the subject
# of the previous assistant turn. Without resolution, the retriever embeds
# "that" as a generic term with no semantic content.
_AMBIGUOUS_PRONOUNS = {"that", "it", "this", "these", "those", "they", "them"}

# Number of recent messages (user + assistant) to include as rewrite context.
# 6 messages = 3 full turns. More context improves resolution accuracy;
# more tokens increases prompt latency. 6 is the practical ceiling for a
# compliance conversation where each turn averages 200–400 tokens.
_MAX_HISTORY_MESSAGES = 6

# Maximum tokens for the rewrite response — a resolved query is 10–30 words,
# 100 tokens is generous headroom without opening the door to verbose output.
_MAX_REWRITE_TOKENS = 100


def _needs_enrichment(query: str, history: list) -> bool:
    """Return True only when enrichment adds value.

    Three fast bypass conditions keep the hot path free of Bedrock calls:
      1. No history — first conversation turn, nothing to resolve against.
      2. Query is 8+ words — long queries are typically self-contained;
         a user who writes "What does AC-6 require for account management in
         federal information systems?" has provided all context inline.
      3. No ambiguous pronouns — query contains no words that require prior
         context to interpret. Skips enrichment on explicit follow-ups like
         "What about AU-12?" which are short but already self-contained.
    """
    if not history:
        return False  # first turn — no prior context to resolve against
    if len(query.split()) >= 8:
        return False  # self-contained by length heuristic
    words = set(query.lower().split())
    return bool(words.intersection(_AMBIGUOUS_PRONOUNS))


def enrich_query(query: str, history: Optional[list] = None) -> str:
    """Rewrite query to be self-contained using recent conversation context.

    Resolves pronouns and vague references before the query reaches the
    embedding call — the retriever embeds a fully specified query rather than
    an ambiguous one. Uses Claude via Bedrock at temperature 0.0 for
    deterministic rewrites.

    Example:
        Turn 1: "What does AC-6 require?"
        Turn 2: "How does that relate to least privilege?"
        Enriched: "How does AC-6 relate to least privilege in NIST 800-53?"

    Bypass: returns original query unchanged when no enrichment is needed
    (no history, long query, or no ambiguous pronouns). All exceptions are
    caught — enrichment failure never blocks the pipeline.

    Args:
        query:   Scrubbed query string (PII already removed).
        history: List of conversation message dicts with "role" and "content"
                 keys. Extra keys (sources, metadata) are ignored.

    Returns:
        Rewritten query string, or original query if bypass or failure.

    see docs/decision_log.md DL-025
    """
    if not _needs_enrichment(query, history or []):
        return query

    # Build compact context from last N messages — role: content format.
    # Truncate long turns to 300 chars to control prompt size;
    # compliance answers are verbose but the key entities (control IDs,
    # framework names) appear in the first paragraph.
    recent = (history or [])[-_MAX_HISTORY_MESSAGES:]
    context_lines = [
        f"{m['role'].capitalize()}: {m.get('content', '')[:300]}"
        for m in recent
        if m.get("content")
    ]
    context_str = "\n".join(context_lines)

    prompt = (
        "Rewrite the following query to be fully self-contained using the "
        "conversation context. Replace pronouns and vague references with "
        "their specific referents. Output only the rewritten query — no "
        "explanation, no preamble, no quotes.\n\n"
        f"Conversation context:\n{context_str}\n\n"
        f"Query: {query}\n"
        "Rewritten query:"
    )

    try:
        bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
        response = bedrock.converse(
            modelId=GENERATION_MODEL,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"temperature": 0.0, "maxTokens": _MAX_REWRITE_TOKENS},
        )
        enriched = response["output"]["message"]["content"][0]["text"].strip()

        # Sanity guard — reject implausibly long or empty rewrites.
        # Rewrite should be close in length to the original plus resolved referents.
        # 5x original length suggests the LLM added explanation despite instructions.
        if not enriched or len(enriched) > max(len(query) * 5, 200):
            logger.warning(
                "enrich_query: rewrite length suspicious (orig=%d, rewrite=%d), "
                "using original", len(query), len(enriched),
            )
            return query

        logger.info("enrich_query: %r → %r", query, enriched[:100])
        return enriched

    except Exception as exc:
        # Best-effort — enrichment failure never blocks retrieval.
        # Common failure modes: Bedrock not configured, quota exceeded,
        # model endpoint unavailable. All fall back to original query.
        logger.warning("enrich_query: rewrite failed (%s), using original query", exc)
        return query
