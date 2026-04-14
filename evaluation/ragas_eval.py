"""RAGAs evaluation — semantic-only vs hybrid retrieval comparison.

Runs the full pipeline in both modes over the 20-question golden dataset
and scores each mode on four RAGAs metrics. Outputs a comparison table
and saves results to data/ragas_results.json.

Cost note: 20 questions x 2 modes = 40 Claude generation calls + 40 OpenAI
embed calls + RAGAs own LLM calls for scoring. Run once after pipeline is
validated. Estimated cost: ~$2-4 USD total.

see docs/decision_log.md DL-009
"""
import json
import logging
from pathlib import Path

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)

from pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
RESULTS_PATH = Path("data/ragas_results.json")

METRICS = [faithfulness, answer_relevancy, context_precision, context_recall]


def load_golden_dataset() -> list[dict]:
    """Load positive questions from golden dataset — excludes negative test entries.
    Negative entries (test_type='negative') are used by guardrail_test.py, not RAGAs."""
    with open(GOLDEN_DATASET_PATH) as f:
        dataset = json.load(f)
    positive = [q for q in dataset if q.get("test_type") != "negative"]
    logger.info(
        "Loaded %d positive questions from golden dataset (%d total, %d negative excluded)",
        len(positive), len(dataset), len(dataset) - len(positive),
    )
    return positive


def run_eval_pipeline(questions: list[dict], use_hybrid: bool) -> list[dict]:
    """Run pipeline for every question in the golden dataset.
    Returns list of dicts ready for RAGAs Dataset construction."""
    mode = "hybrid" if use_hybrid else "semantic"
    logger.info("Running %s pipeline for %d questions...", mode, len(questions))

    results = []
    for i, item in enumerate(questions, 1):
        logger.info("[%d/%d] %s | %s", i, len(questions), mode, item["question"][:60])
        output = run_pipeline(item["question"], use_hybrid=use_hybrid)
        results.append({
            "question": item["question"],
            "answer": output["answer"],
            # RAGAs expects contexts as list of strings — one string per chunk
            "contexts": [c["text"] for c in output["chunks"]],
            "ground_truth": item["reference_answer"],
            "source": item["source"],
            "id": item["id"],
        })

    return results


def build_ragas_dataset(results: list[dict]) -> Dataset:
    """Convert pipeline results to HuggingFace Dataset for RAGAs."""
    return Dataset.from_dict({
        "question": [r["question"] for r in results],
        "answer": [r["answer"] for r in results],
        "contexts": [r["contexts"] for r in results],
        "ground_truth": [r["ground_truth"] for r in results],
    })


def _mean(val) -> float:
    """Extract scalar mean from a RAGAs metric result.
    Newer RAGAs versions return a list of per-question scores instead of
    a pre-aggregated float — handle both."""
    if isinstance(val, (int, float)):
        return float(val)
    valid = [float(v) for v in val if v is not None]
    return sum(valid) / max(len(valid), 1)


def score_dataset(dataset: Dataset) -> dict:
    """Run RAGAs evaluation on the dataset. Returns metric scores as floats.
    RAGAs uses OpenAI internally for faithfulness and answer_relevancy scoring —
    OPENAI_API_KEY must be set in .env."""
    result = evaluate(dataset, metrics=METRICS)
    return {
        "faithfulness": round(_mean(result["faithfulness"]), 4),
        "answer_relevancy": round(_mean(result["answer_relevancy"]), 4),
        "context_precision": round(_mean(result["context_precision"]), 4),
        "context_recall": round(_mean(result["context_recall"]), 4),
    }


def print_comparison(semantic_scores: dict, hybrid_scores: dict) -> None:
    """Print side-by-side comparison table."""
    print("\n" + "=" * 62)
    print(f"{'Metric':<25} {'Semantic':>10} {'Hybrid':>10} {'Delta':>10}")
    print("=" * 62)
    for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        sem = semantic_scores[metric]
        hyb = hybrid_scores[metric]
        delta = hyb - sem
        sign = "+" if delta >= 0 else ""
        print(f"{metric:<25} {sem:>10.4f} {hyb:>10.4f} {sign}{delta:>9.4f}")
    print("=" * 62 + "\n")


def main() -> None:
    questions = load_golden_dataset()

    # semantic baseline
    semantic_results = run_eval_pipeline(questions, use_hybrid=False)
    semantic_scores = score_dataset(build_ragas_dataset(semantic_results))
    logger.info("Semantic scores: %s", semantic_scores)

    # hybrid
    hybrid_results = run_eval_pipeline(questions, use_hybrid=True)
    hybrid_scores = score_dataset(build_ragas_dataset(hybrid_results))
    logger.info("Hybrid scores: %s", hybrid_scores)

    print_comparison(semantic_scores, hybrid_scores)

    # save full results for record and future analysis
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "semantic": {"scores": semantic_scores, "results": semantic_results},
        "hybrid": {"scores": hybrid_scores, "results": hybrid_results},
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2)
    logger.info("Results saved to %s", RESULTS_PATH)


if __name__ == "__main__":
    main()
