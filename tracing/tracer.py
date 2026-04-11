from langfuse import Langfuse

from config import LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST


def get_langfuse() -> Langfuse:
    """Initialize Langfuse client — host read from LANGFUSE_HOST in config (Cloud or self-hosted).
    see docs/decision_log.md DL-006"""
    return Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        host=LANGFUSE_HOST,
    )
