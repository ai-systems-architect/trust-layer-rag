import logging
from pathlib import Path

import boto3

from config import (
    AWS_REGION,
    GENERATION_MODEL,
    BEDROCK_GUARDRAIL_ID,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# System prompt — governs answer tone, scope, and citation behavior
# see prompts/system_prompt.txt
_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "system_prompt.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text().strip()


def build_user_message(query: str, chunks: list[dict]) -> str:
    """Assemble context + query into the user turn.
    Each chunk is labeled with source and page for citation traceability."""
    context_blocks = []
    for i, chunk in enumerate(chunks, 1):
        label = f"[{i}] {chunk['display_name']} — page {chunk.get('page', 'N/A')}"
        context_blocks.append(f"{label}\n{chunk['text']}")

    context = "\n\n---\n\n".join(context_blocks)
    return (
        f"Use the following compliance document excerpts to answer the question.\n\n"
        f"{context}\n\n"
        f"Question: {query}"
    )


def generate(query: str, chunks: list[dict]) -> dict:
    """Call Claude 3.5 Sonnet via Bedrock converse API with Guardrails.
    Guardrails applied when BEDROCK_GUARDRAIL_ID is set — prevents overclaiming
    in federal compliance context.
    see docs/decision_log.md DL-004"""
    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    user_message = build_user_message(query, chunks)

    request_kwargs = {
        "modelId": GENERATION_MODEL,
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": [{"text": user_message}]}],
    }

    # attach guardrails only if configured — avoids error when ID not yet provisioned
    if BEDROCK_GUARDRAIL_ID:
        request_kwargs["guardrailConfig"] = {
            "guardrailIdentifier": BEDROCK_GUARDRAIL_ID,
            "guardrailVersion": "DRAFT",
            "trace": "enabled",
        }

    response = client.converse(**request_kwargs)

    answer = response["output"]["message"]["content"][0]["text"]
    stop_reason = response.get("stopReason", "end_turn")

    # guardrail intervention logged — "none" means no intervention
    guardrail_action = "none"
    if "trace" in response:
        guardrail_action = (
            response["trace"]
            .get("guardrail", {})
            .get("outputAssessments", {})
            .get("action", "none")
        )

    logger.info(
        "generate: model=%s stop_reason=%s guardrail_action=%s",
        GENERATION_MODEL, stop_reason, guardrail_action,
    )

    return {
        "answer": answer,
        "model": GENERATION_MODEL,
        "stop_reason": stop_reason,
        "guardrail_action": guardrail_action,
    }
