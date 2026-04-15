import logging
from pathlib import Path
import boto3
from pydantic import BaseModel, field_validator

from config import (
    AWS_REGION,
    GENERATION_MODEL,
    BEDROCK_GUARDRAIL_ID,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response validation — Pydantic model for generate() output
# Validates structure before the dict reaches pipeline.py. Raises
# ValidationError on unexpected Bedrock API shape changes rather than
# propagating a silent bad value downstream.
# see docs/decision_log.md DL-004
# ---------------------------------------------------------------------------

_KNOWN_STOP_REASONS = {"end_turn", "max_tokens", "guardrail_intervened", "content_filtered"}


class GenerateResponse(BaseModel):
    answer: str
    model: str
    stop_reason: str
    guardrail_action: str

    @field_validator("answer")
    @classmethod
    def answer_not_empty(cls, v: str) -> str:
        if not v or len(v.strip()) < 10:
            raise ValueError(f"answer too short or empty: {v!r}")
        return v

    @field_validator("stop_reason")
    @classmethod
    def stop_reason_known(cls, v: str) -> str:
        if v not in _KNOWN_STOP_REASONS:
            # log a warning but do not raise — Bedrock may add new values
            logger.warning(
                "generate: unexpected stop_reason %r — expected one of %s", v, _KNOWN_STOP_REASONS
            )
        return v


# ---------------------------------------------------------------------------
# Input guardrail — standalone check via apply_guardrail API
# Separate from the converse guardrailConfig (which runs at generation time).
# apply_guardrail lets the pipeline short-circuit BEFORE retrieval fires —
# no pgvector query, no Cohere call, no Bedrock generation invocation.
#
# source="INPUT"  — query check in pipeline.py before retrieval
# source="OUTPUT" — handled inline by converse guardrailConfig in generate()
#
# apply_guardrail quota note: each call counts against Bedrock guardrail
# quota (~50–100ms latency). In high-volume production, a lightweight
# keyword pre-filter should gate the Bedrock call to reduce cost and latency.
# see docs/decision_log.md DL-022
# ---------------------------------------------------------------------------


def check_guardrail(text: str, source: str = "INPUT") -> dict:
    """Apply Bedrock Guardrail to text at a specified pipeline stage.
    Returns {"action": str, "blocked": bool}.

    No-ops if BEDROCK_GUARDRAIL_ID is not configured — allows the pipeline
    to run without guardrails in development environments.
    source must be 'INPUT' or 'OUTPUT' per Bedrock apply_guardrail API."""
    if not BEDROCK_GUARDRAIL_ID:
        return {"action": "NONE", "blocked": False}

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    response = client.apply_guardrail(
        guardrailIdentifier=BEDROCK_GUARDRAIL_ID,
        guardrailVersion="DRAFT",
        source=source,
        content=[{"text": {"text": text}}],
    )
    action = response.get("action", "NONE")
    blocked = action == "GUARDRAIL_INTERVENED"
    logger.info("check_guardrail: source=%s action=%s", source, action)
    return {"action": action, "blocked": blocked}


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
    """Call Claude Sonnet 4.5 via Bedrock converse API with Guardrails.
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

    # validate response structure — raises ValidationError on bad shape
    validated = GenerateResponse(
        answer=answer,
        model=GENERATION_MODEL,
        stop_reason=stop_reason,
        guardrail_action=guardrail_action,
    )
    return validated.model_dump()
