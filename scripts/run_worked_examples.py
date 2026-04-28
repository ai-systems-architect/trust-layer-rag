"""Re-run the six worked examples (MAIN-1..3, NEG-1..3) with debug instrumentation.

Sets DEBUG_PIPELINE=true before importing pipeline so the env-gated debug blocks fire
and print formatted RETRIEVE/RERANK/SUMMARY tables for each query. Output is suitable
for pasting into README.md "Worked Examples" tables when regenerating documentation
after pipeline or corpus changes.

Usage:
    PYTHONPATH=. python scripts/run_worked_examples.py

Requires RDS to be running. Cost: 6 queries × (OpenAI embedding + Cohere rerank +
Bedrock generate) — non-trivial but only run when worked examples need a refresh.

To capture only one example, run pipeline.py directly:
    DEBUG_PIPELINE=true PYTHONPATH=. python pipeline.py "<query>"

see docs/decision_log.md DL-029
"""
import os

os.environ["DEBUG_PIPELINE"] = "true"

from pipeline import run_pipeline  # noqa: E402 — env var must be set before import


QUERIES = [
    (
        "MAIN-1 Control ID lookup",
        "What does AC-6 require and what are its key enhancements?",
    ),
    (
        "MAIN-2 AI governance",
        "How does the AI RMF Govern function establish organizational accountability "
        "for AI risk?",
    ),
    (
        "MAIN-3 Cross-corpus synthesis",
        "How do FedRAMP access control requirements relate to NIST AI RMF governance "
        "expectations?",
    ),
    (
        "NEG-1 Quantum key rotation",
        "What does NIST 800-53 say about quantum computing key rotation schedules?",
    ),
    (
        "NEG-2 Cryptocurrency FedRAMP",
        "How should AI systems handle cryptocurrency transaction validation under FedRAMP?",
    ),
    (
        "NEG-3 Blockchain smart contracts",
        "What are the NIST guidelines for blockchain smart contract auditing?",
    ),
]


if __name__ == "__main__":
    for label, query in QUERIES:
        print(f"\n{'#' * 72}")
        print(f"# {label}")
        print(f"# Query: {query}")
        print(f"{'#' * 72}")
        run_pipeline(query, use_hybrid=True)
        print()
