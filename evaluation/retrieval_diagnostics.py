"""Retrieval diagnostics — Recall@k, MRR, nDCG across three pipeline configurations.

Measures retrieval quality independently of generation — whether the retriever finds
the right chunks before Claude runs. Complements RAGAs evaluation (DL-020), which
measures end-to-end answer quality including generation behavior.

Three configurations compared:
  Semantic        — dense pgvector HNSW, top-10
  Hybrid          — dense + BM25 + RRF fusion, top-10
  Hybrid+Rerank   — hybrid top-10 → Cohere cross-encoder, top-5

Prerequisite: run evaluation/label_chunks.py first to populate relevant_chunk_ids
in golden_dataset.json. This script will exit early if labels are missing.

Results saved to data/retrieval_diagnostics.json.

see docs/evaluation_methodology.md for metric definitions and labeling rationale
see docs/decision_log.md DL-021
"""
import json
import logging
import math
import time
from pathlib import Path

from retrieval.semantic import semantic_search
from retrieval.hybrid import hybrid_search
from retrieval.rerank import rerank
from config import TOP_K_RETRIEVAL, TOP_K_RERANK

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
RESULTS_PATH = Path("data/retrieval_diagnostics.json")

# Evaluation depths — Recall and MRR reported at both k=5 and k=10.
# k=5 aligns with post-rerank top-k (TOP_K_RERANK). k=10 is the pre-rerank pool.
RECALL_K = [5, 10]
MRR_K = 10
NDCG_K = 5

# Query type mapping — used to segment results in the comparison table.
# Based on which corpus source each question comes from.
SOURCE_TO_TYPE = {
    "NIST 800-53": "Control ID",
    "FedRAMP": "Control ID",
    "NIST AI RMF": "Governance",
    "NIST AI 600-1": "Governance",
    "Cross-corpus": "Cross-corpus",
}


# ---------------------------------------------------------------------------
# Metric implementations
# ---------------------------------------------------------------------------

def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of known relevant chunks appearing in top-k retrieved results.
    Returns 0.0 if relevant_ids is empty — prevents division by zero."""
    if not relevant_ids:
        return 0.0
    retrieved_top_k = set(retrieved_ids[:k])
    return len(retrieved_top_k & relevant_ids) / len(relevant_ids)


def mrr(retrieved_ids: list[str], relevant_ids: set[str], k: int = MRR_K) -> float:
    """Reciprocal rank of the first relevant chunk in the result list.
    Returns 0.0 if no relevant chunk appears in top-k.

    MRR is computed per-question; the caller averages across questions.
    Evaluating at k=MRR_K (10) rather than k=5 because MRR on a truncated
    list underestimates rank quality — a relevant chunk at rank 6 counts in
    the pre-rerank config (top-10) but would be invisible at k=5."""
    for rank, chunk_id in enumerate(retrieved_ids[:k], start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int = NDCG_K) -> float:
    """Normalized Discounted Cumulative Gain at k.

    DCG@k  = Σ rel_i / log₂(i+1)   for i=1..k, rel_i ∈ {0,1}
    IDCG@k = DCG of perfect ranking (all relevant chunks at top positions)
    nDCG@k = DCG@k / IDCG@k

    Binary relevance — chunk is either relevant (1) or not (0).
    Returns 0.0 if relevant_ids is empty."""
    if not relevant_ids:
        return 0.0

    # actual DCG
    dcg = 0.0
    for i, chunk_id in enumerate(retrieved_ids[:k], start=1):
        if chunk_id in relevant_ids:
            dcg += 1.0 / math.log2(i + 1)

    # ideal DCG — number of relevant chunks we could have found in top-k
    ideal_count = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_count + 1))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_labeled_questions() -> list[dict]:
    """Load positive questions that have been labeled with relevant_chunk_ids.
    Exits early with a clear message if labeling has not been run yet."""
    with open(GOLDEN_DATASET_PATH) as f:
        dataset = json.load(f)

    positives = [q for q in dataset if q.get("test_type") != "negative"]
    unlabeled = [q for q in positives if "relevant_chunk_ids" not in q]

    if unlabeled:
        raise RuntimeError(
            f"{len(unlabeled)} questions missing relevant_chunk_ids. "
            "Run evaluation/label_chunks.py first."
        )

    logger.info("Loaded %d labeled questions", len(positives))
    return positives


# ---------------------------------------------------------------------------
# Retrieval runners — one per configuration
# ---------------------------------------------------------------------------

def run_semantic(question: str) -> list[str]:
    """Dense pgvector HNSW retrieval, top-10. Returns ordered chunk_id list."""
    results = semantic_search(question, top_k=TOP_K_RETRIEVAL)
    return [r["chunk_id"] for r in results]


def run_hybrid(question: str) -> list[str]:
    """Dense + BM25 + RRF fusion, top-10. Returns ordered chunk_id list."""
    results = hybrid_search(question, top_k=TOP_K_RETRIEVAL)
    return [r["chunk_id"] for r in results]


def run_hybrid_rerank(question: str) -> list[str]:
    """Hybrid top-10 → Cohere cross-encoder top-5. Returns ordered chunk_id list.
    Reranker narrows to TOP_K_RERANK — Recall@10 is not meaningful for this config
    since only 5 chunks are returned. Recall@5 and MRR@5 are the relevant metrics."""
    chunks = hybrid_search(question, top_k=TOP_K_RETRIEVAL)
    reranked = rerank(question, chunks, top_k=TOP_K_RERANK)
    return [r["chunk_id"] for r in reranked]


# ---------------------------------------------------------------------------
# Evaluation loop
# ---------------------------------------------------------------------------

def evaluate_config(
    questions: list[dict],
    retriever_fn,
    config_name: str,
    inter_query_delay: float = 0.0,
) -> list[dict]:
    """Run one retrieval configuration over all questions and compute per-question metrics.

    inter_query_delay — seconds to sleep between questions. Required for Cohere trial
    keys (10 calls/minute limit). Set to 7.0 for hybrid_rerank config on trial keys."""
    results = []
    for i, item in enumerate(questions, 1):
        logger.info("[%d/%d] %s | %s", i, len(questions), config_name, item["question"][:60])
        if inter_query_delay > 0 and i > 1:
            time.sleep(inter_query_delay)
        retrieved_ids = retriever_fn(item["question"])
        relevant_ids = set(item["relevant_chunk_ids"])

        result = {
            "id": item["id"],
            "source": item["source"],
            "query_type": SOURCE_TO_TYPE.get(item["source"], "Other"),
            "config": config_name,
            "retrieved_ids": retrieved_ids,
            "relevant_ids": list(relevant_ids),
        }
        for k in RECALL_K:
            result[f"recall@{k}"] = round(recall_at_k(retrieved_ids, relevant_ids, k), 4)
        result["mrr"] = round(mrr(retrieved_ids, relevant_ids), 4)
        result["ndcg@5"] = round(ndcg_at_k(retrieved_ids, relevant_ids, NDCG_K), 4)

        results.append(result)

    return results


def aggregate(results: list[dict], metric: str) -> float:
    """Mean of a metric across all results in a list."""
    vals = [r[metric] for r in results]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_comparison(
    sem: list[dict],
    hyb: list[dict],
    h_r: list[dict],
) -> None:
    """Print the 6-column comparison table segmented by query type.

    Columns: Recall@5 (all 3 configs) + MRR (all 3 configs).
    MRR Hybrid is the most architecturally informative column — isolates RRF
    fusion contribution independently of Cohere reranking. See DL-021."""

    query_types = ["Control ID", "Governance", "Cross-corpus"]
    configs = [("Semantic", sem), ("Hybrid", hyb), ("H+Rerank", h_r)]

    header = f"{'Query Type':<18}"
    for label, _ in configs:
        header += f" {'R@5 ' + label:>12}"
    for label, _ in configs:
        header += f" {'MRR ' + label:>12}"

    print("\n" + "=" * (18 + 12 * 6 + 6))
    print(header)
    print("=" * (18 + 12 * 6 + 6))

    all_rows = [("All queries", None)]
    for qt in query_types:
        all_rows.append((qt, qt))

    for label, qt_filter in all_rows:
        if qt_filter is None:
            sem_q, hyb_q, h_r_q = sem, hyb, h_r
        else:
            sem_q = [r for r in sem if r["query_type"] == qt_filter]
            hyb_q = [r for r in hyb if r["query_type"] == qt_filter]
            h_r_q = [r for r in h_r if r["query_type"] == qt_filter]
            if not sem_q:
                continue

        row = f"{label:<18}"
        for data in [sem_q, hyb_q, h_r_q]:
            row += f" {aggregate(data, 'recall@5'):>12.4f}"
        for data in [sem_q, hyb_q, h_r_q]:
            row += f" {aggregate(data, 'mrr'):>12.4f}"
        print(row)

    print("=" * (18 + 12 * 6 + 6))

    # nDCG summary row
    print(
        f"\nnDCG@5 — Semantic: {aggregate(sem, 'ndcg@5'):.4f} | "
        f"Hybrid: {aggregate(hyb, 'ndcg@5'):.4f} | "
        f"Hybrid+Rerank: {aggregate(h_r, 'ndcg@5'):.4f}\n"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    questions = load_labeled_questions()

    logger.info("Running semantic retrieval...")
    sem_results = evaluate_config(questions, run_semantic, "semantic")

    logger.info("Running hybrid retrieval...")
    hyb_results = evaluate_config(questions, run_hybrid, "hybrid")

    logger.info("Running hybrid + rerank...")
    # 7s inter-query delay — Cohere trial key limit is 10 calls/minute
    h_r_results = evaluate_config(
        questions, run_hybrid_rerank, "hybrid_rerank", inter_query_delay=7.0
    )

    print_comparison(sem_results, hyb_results, h_r_results)

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "semantic": sem_results,
        "hybrid": hyb_results,
        "hybrid_rerank": h_r_results,
        "summary": {
            "semantic": {
                m: aggregate(sem_results, m)
                for m in ["recall@5", "recall@10", "mrr", "ndcg@5"]
            },
            "hybrid": {
                m: aggregate(hyb_results, m)
                for m in ["recall@5", "recall@10", "mrr", "ndcg@5"]
            },
            "hybrid_rerank": {
                m: aggregate(h_r_results, m)
                for m in ["recall@5", "recall@10", "mrr", "ndcg@5"]
            },
        },
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Results saved to %s", RESULTS_PATH)


if __name__ == "__main__":
    main()
