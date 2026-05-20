"""One-time ground truth labeling — adds relevant_chunk_ids to golden_dataset.json.

For each positive question in the golden dataset, identifies which chunk IDs should
be retrieved. These become the ground truth labels for Recall@k, MRR, and nDCG
computation in retrieval_diagnostics.py.

Labeling methodology (auto-labeling from reference answers):
1. Run broad retrieval: semantic top-30 + BM25 top-30 per question, deduplicated.
   Using both retrieval legs as the candidate pool avoids systematic bias toward
   either retrieval method during labeling.
2. Compute token Jaccard overlap between each candidate chunk and the reference_answer.
   Chunks with overlap >= OVERLAP_THRESHOLD are labeled relevant.
3. For control ID queries: any chunk containing an explicit control identifier
   (AC-6, AU-2, IR-4, etc.) found in the question is labeled relevant regardless
   of overlap score. Control ID match is a high-confidence signal independent of
   text overlap.

Labeling limitation: labels are seeded from the embedding space (semantic search
in the candidate pool) and reference answers written in similar vocabulary to the
corpus. Semantic Recall@k may be slightly optimistic. Hybrid and rerank improvements
relative to semantic remain valid architectural comparisons.

Run once after initial corpus ingestion. Re-run if corpus or questions change.

see docs/evaluation_methodology.md for full labeling rationale
see docs/decision_log.md DL-021
"""
import json
import logging
import re
from pathlib import Path

from retrieval.semantic import semantic_search, get_connection
from retrieval.hybrid import sparse_search, _sparse_query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"

# Token Jaccard overlap threshold — chunk must share >= this fraction of tokens
# with the reference_answer to be labeled relevant.
# Calibrated on compliance corpus: 0.07 captures substantive overlap (shared control
# terminology, NIST citations) without over-labeling loosely related chunks.
OVERLAP_THRESHOLD = 0.07

# Broad retrieval pool size — larger than evaluation top-k to ensure relevant chunks
# are reachable even if they don't rank in the top-10.
CANDIDATE_TOP_K = 30

# Control ID pattern — matches AC-6, AU-2, IR-4, SC-28, AU-12(3), MAP-1.1, CM-7
# Same pattern used in retrieval/hybrid.py _sparse_query() — kept consistent.
_CONTROL_ID_RE = re.compile(r'\b[A-Z]{1,3}-\d+(?:\(\d+\))?(?:\.\d+)?\b')


def tokenize(text: str) -> set[str]:
    """Lowercase alpha tokens of length >= 3 — same vocabulary as BM25 preprocessing."""
    return set(re.findall(r'\b[a-z]{3,}\b', text.lower()))


def jaccard_overlap(text_a: str, text_b: str) -> float:
    """Token Jaccard similarity: |A ∩ B| / |A ∪ B|."""
    a = tokenize(text_a)
    b = tokenize(text_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def extract_control_ids(text: str) -> list[str]:
    """Extract explicit control identifiers from question or reference answer."""
    return _CONTROL_ID_RE.findall(text)


def get_candidate_chunks(question: str) -> list[dict]:
    """Broad retrieval: semantic top-30 + BM25 top-30, deduplicated by chunk_id.
    Union of both retrieval legs ensures neither method is systematically excluded
    from the candidate pool during labeling."""
    # semantic candidates
    semantic_chunks = semantic_search(question, top_k=CANDIDATE_TOP_K)

    # sparse candidates — preprocess query same way as production
    conn = get_connection()
    sparse_q = _sparse_query(question)
    try:
        sparse_chunks = sparse_search(conn, sparse_q, top_k=CANDIDATE_TOP_K)
    finally:
        conn.close()

    # deduplicate by chunk_id — first occurrence wins (semantic results are pre-scored)
    seen = set()
    candidates = []
    for chunk in semantic_chunks + sparse_chunks:
        cid = chunk["chunk_id"]
        if cid not in seen:
            seen.add(cid)
            candidates.append(chunk)

    logger.debug(
        "candidates: semantic=%d sparse=%d deduplicated=%d sparse_query=%r",
        len(semantic_chunks), len(sparse_chunks), len(candidates), sparse_q,
    )
    return candidates


def label_question(item: dict) -> list[str]:
    """Identify relevant chunk IDs for one question.

    A chunk is labeled relevant if either condition holds:
    1. Token Jaccard overlap with reference_answer >= OVERLAP_THRESHOLD
    2. Chunk text contains a control ID explicitly mentioned in the question
       (high-confidence signal regardless of overlap score)
    """
    reference = item["reference_answer"]
    question = item["question"]
    control_ids_in_question = extract_control_ids(question)

    candidates = get_candidate_chunks(question)
    relevant_ids = []

    for chunk in candidates:
        chunk_text = chunk["text"]

        # signal 1: text overlap with reference answer
        overlap = jaccard_overlap(chunk_text, reference)
        if overlap >= OVERLAP_THRESHOLD:
            relevant_ids.append(chunk["chunk_id"])
            continue

        # signal 2: control ID match — chunk contains an ID explicitly in the question
        if control_ids_in_question:
            chunk_control_ids = extract_control_ids(chunk_text)
            if any(cid in chunk_control_ids for cid in control_ids_in_question):
                relevant_ids.append(chunk["chunk_id"])

    return relevant_ids


def main() -> None:
    """Label all positive questions and write relevant_chunk_ids back to golden_dataset.json.
    Negative test entries (test_type='negative') are skipped — no relevant chunks apply."""
    with open(GOLDEN_DATASET_PATH) as f:
        dataset = json.load(f)

    positives = [q for q in dataset if q.get("test_type") != "negative"]
    negatives = [q for q in dataset if q.get("test_type") == "negative"]

    logger.info(
        "Labeling %d positive questions (%d negative entries skipped)",
        len(positives), len(negatives),
    )

    labeled = 0
    for i, item in enumerate(positives, 1):
        logger.info("[%d/%d] %s", i, len(positives), item["question"][:70])
        relevant_ids = label_question(item)
        item["relevant_chunk_ids"] = relevant_ids
        logger.info("  → %d relevant chunks (source=%s)", len(relevant_ids), item["source"])
        if len(relevant_ids) == 0:
            logger.warning("  ⚠ zero relevant chunks for id=%d — review threshold", item["id"])
        labeled += 1

    # merge positives (now labeled) back with negatives (unchanged)
    all_entries = positives + negatives
    all_entries.sort(key=lambda x: x["id"])

    with open(GOLDEN_DATASET_PATH, "w") as f:
        json.dump(all_entries, f, indent=2)

    logger.info("Labeled %d questions. Updated %s", labeled, GOLDEN_DATASET_PATH)


if __name__ == "__main__":
    main()
