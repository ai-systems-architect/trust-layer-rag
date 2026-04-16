import logging
import re
from typing import Optional

from config import TOP_K_RETRIEVAL, MIN_RRF_SCORE, MIN_RRF_CANDIDATES
from retrieval.semantic import embed_query, get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# RRF_K=60 — standard value, empirically stable across retrieval benchmarks.
# Lower k (e.g. 10) amplifies top-rank differences — brittle on small corpora.
# Higher k (e.g. 100) flattens scores — loses signal between rank 1 and rank 10.
# k=60 requires no tuning at this corpus size.
# see docs/decision_log.md DL-008
RRF_K = 60

# Stop words stripped before sparse search — see DL-019
_STOP_WORDS = {
    'what', 'which', 'how', 'why', 'when', 'where', 'who',
    'does', 'should', 'would', 'could', 'are', 'the', 'and',
    'for', 'that', 'this', 'with', 'from', 'they', 'have',
    'been', 'their', 'its', 'not', 'but', 'can', 'was',
}


def _sparse_query(query: str, max_terms: int = 5) -> str:
    """Extract top N meaningful terms for BM25 sparse search.
    plainto_tsquery ANDs all terms — long queries return 0 results if any
    single term is absent from a chunk. Tested thresholds on compliance corpus:
    4 terms = 24 results, 5 terms = 8 results, 6 terms = 2 results.
    5 is the sweet spot — precise without collapsing recall.

    Control IDs (AC-2, IR-4, MAP-1.1) are extracted from the original query
    before any lowercasing or term limiting. Lowercasing destroys the uppercase
    pattern; the alpha-only regex then splits AC-2 into 'ac' (no signal) and
    drops '2' entirely. Pre-extraction preserves the full identifier as a
    high-value BM25 anchor regardless of its position in the query.
    see docs/decision_log.md DL-019"""
    # step 1: extract control identifiers from original query before lowercasing.
    # pattern covers: AC-2, IR-4, SC-28, AU-12(3), MAP-1.1, CM-7
    # must run on original query — lowercasing destroys the uppercase pattern
    control_ids = re.findall(r'\b[A-Z]{1,3}-\d+(?:\(\d+\))?(?:\.\d+)?\b', query)
    control_ids = list(dict.fromkeys(control_ids))  # deduplicate, preserve order

    # step 2: fill remaining slots with stop-word-stripped regular terms.
    # control IDs take priority — they occupy the first slots in the term list
    remaining_slots = max(max_terms - len(control_ids), 0)
    words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
    terms = [w for w in words if w not in _STOP_WORDS]
    regular_terms = list(dict.fromkeys(terms))[:remaining_slots]

    return ' '.join(control_ids + regular_terms)


def _build_where(
    extra_clauses: list[str],
    base_clause: str = "",
) -> str:
    """Combine a mandatory base clause with optional metadata filter clauses.

    base_clause is the tsvector match expression (sparse leg only) — always
    present when supplied. extra_clauses are metadata AND conditions appended
    on top. Returns a complete WHERE ... string or empty string if nothing
    to filter on.
    """
    all_clauses = ([base_clause] if base_clause else []) + extra_clauses
    return ("WHERE " + " AND ".join(all_clauses)) if all_clauses else ""


def dense_search(
    conn,
    vector: list[float],
    top_k: int,
    source: Optional[str] = None,
    control_family: Optional[str] = None,
    impact_level: Optional[str] = None,
) -> list[dict]:
    """pgvector HNSW cosine search — dense retrieval leg.

    Optional metadata pre-filters applied before the HNSW sweep.
    Filters are AND-combined; None values are skipped.
    see docs/decision_log.md DL-023"""
    filter_clauses: list[str] = []
    filter_params: list = []

    if source is not None:
        filter_clauses.append("source = %s")
        filter_params.append(source)
    if control_family is not None:
        filter_clauses.append("control_family = %s")
        filter_params.append(control_family)
    if impact_level is not None:
        filter_clauses.append("impact_level = %s")
        filter_params.append(impact_level)

    where_sql = _build_where(filter_clauses)
    sql = f"""
        SELECT chunk_id, source, display_name, page, chunk_index, text
        FROM chunks
        {where_sql}
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """
    params = filter_params + [vector, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "chunk_id": row[0],
            "source": row[1],
            "display_name": row[2],
            "page": row[3],
            "chunk_index": row[4],
            "text": row[5],
        }
        for row in rows
    ]


def sparse_search(
    conn,
    query: str,
    top_k: int,
    source: Optional[str] = None,
    control_family: Optional[str] = None,
    impact_level: Optional[str] = None,
) -> list[dict]:
    """tsvector GIN BM25-style keyword search — sparse retrieval leg.

    plainto_tsquery vs to_tsquery: to_tsquery('access management') throws a
    syntax error on raw input — requires manual 'access & management' syntax.
    plainto_tsquery tokenizes and ANDs terms automatically — safe for
    unstructured compliance queries. websearch_to_tsquery adds OR/NOT/phrase
    support but compliance queries are additive; extra operators add noise,
    not precision.

    Optional metadata pre-filters are ANDed with the tsvector match clause —
    they narrow the full-text candidate set before ts_rank scoring.
    see docs/decision_log.md DL-008, DL-023"""
    filter_clauses: list[str] = []
    filter_params: list = []

    if source is not None:
        filter_clauses.append("source = %s")
        filter_params.append(source)
    if control_family is not None:
        filter_clauses.append("control_family = %s")
        filter_params.append(control_family)
    if impact_level is not None:
        filter_clauses.append("impact_level = %s")
        filter_params.append(impact_level)

    # tsvector match is always the leading WHERE predicate; metadata filters follow
    tsv_clause = "to_tsvector('english', text) @@ plainto_tsquery('english', %s)"
    where_sql = _build_where(filter_clauses, base_clause=tsv_clause)

    sql = f"""
        SELECT chunk_id, source, display_name, page, chunk_index, text
        FROM chunks
        {where_sql}
        ORDER BY ts_rank(
            to_tsvector('english', text),
            plainto_tsquery('english', %s)
        ) DESC
        LIMIT %s;
    """
    # params order: tsv match placeholder, metadata filters, ts_rank placeholder, LIMIT
    params = [query] + filter_params + [query, top_k]

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "chunk_id": row[0],
            "source": row[1],
            "display_name": row[2],
            "page": row[3],
            "chunk_index": row[4],
            "text": row[5],
        }
        for row in rows
    ]


def reciprocal_rank_fusion(
    dense_results: list[dict],
    sparse_results: list[dict],
    k: int = RRF_K,
) -> list[dict]:
    """Merge dense and sparse rank lists via RRF.
    RRF score = 1/(k + rank_dense) + 1/(k + rank_sparse)
    Chunks appearing in both lists score higher — natural precision boost.
    see docs/decision_log.md DL-008"""
    scores: dict[str, float] = {}
    chunks: dict[str, dict] = {}

    for rank, result in enumerate(dense_results, start=1):
        cid = result["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        chunks[cid] = result

    for rank, result in enumerate(sparse_results, start=1):
        cid = result["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
        chunks[cid] = result

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [
        {**chunks[cid], "score": round(score, 6), "retriever": "hybrid"}
        for cid, score in ranked
    ]


def hybrid_search(
    query: str,
    top_k: int = TOP_K_RETRIEVAL,
    source: Optional[str] = None,
    control_family: Optional[str] = None,
    impact_level: Optional[str] = None,
) -> list[dict]:
    """Hybrid retrieval: dense (pgvector) + sparse (tsvector) fused via RRF.

    Both legs retrieve top_k independently; RRF merges and re-ranks the union.
    Optional metadata pre-filters are forwarded to both legs — the same WHERE
    clauses apply to both the HNSW sweep and the tsvector candidate set,
    so only chunks matching the filter participate in RRF scoring.

    Args:
        query:          Natural-language query string.
        top_k:          Maximum results to return after RRF merge.
        source:         Restrict to a single corpus source key.
        control_family: Restrict to a NIST 800-53 control family prefix.
        impact_level:   Restrict to a FedRAMP impact level.

    see docs/decision_log.md DL-008, DL-023
    """
    vector = embed_query(query)
    conn = get_connection()

    # preprocess query for BM25 — control IDs extracted first, then stop word strip
    # log the preprocessed string so sparse=0 cases are diagnosable in Langfuse traces
    sparse_q = _sparse_query(query)

    try:
        dense = dense_search(
            conn, vector, top_k,
            source=source, control_family=control_family, impact_level=impact_level,
        )
        sparse = sparse_search(
            conn, sparse_q, top_k,
            source=source, control_family=control_family, impact_level=impact_level,
        )
    finally:
        conn.close()

    logger.info(
        "hybrid_search: dense=%d sparse=%d sparse_query=%r original_query=%r "
        "| source=%s control_family=%s impact_level=%s",
        len(dense), len(sparse), sparse_q, query[:60],
        source, control_family, impact_level,
    )

    fused = reciprocal_rank_fusion(dense, sparse)

    # --- post-RRF quality gate ---
    # Drop candidates below MIN_RRF_SCORE before passing to Cohere reranker.
    # RRF score reflects how consistently a chunk appeared at the top of both
    # retrieval legs — low scores indicate a chunk surfaced weakly in only one
    # leg at a low rank. Passing weak candidates to Cohere wastes rerank quota
    # and can surface noise in the top-5 if no strong candidates are available.
    #
    # Score context for this corpus (k=60, top_k=10):
    #   0.030+  : appeared in both dense and sparse at high rank (strong signal)
    #   0.0164  : rank 1 in one leg only  (1/(60+1))
    #   0.0143  : rank 10 in one leg only (1/(60+10)) — theoretical minimum
    #
    # MIN_RRF_SCORE=0.0150 drops single-leg tail candidates at ranks 7–10.
    # Empirical results across 7 representative query types: 6–10 candidates
    # pass per query, average 8.1 of 10 — safety floor did not trigger.
    #
    # Safety floor: always pass at least MIN_RRF_CANDIDATES to Cohere.
    # Prevents empty rerank on sparse corpora or heavily filtered candidate sets
    # where no chunk clears the threshold.
    # see docs/decision_log.md DL-024
    filtered = [r for r in fused if r["score"] >= MIN_RRF_SCORE]
    if len(filtered) < MIN_RRF_CANDIDATES:
        # floor triggered — take top N regardless of score
        filtered = fused[:MIN_RRF_CANDIDATES]

    logger.info(
        "post-RRF filter: %d/%d candidates passed threshold=%.4f (floor=%d)",
        len(filtered), len(fused), MIN_RRF_SCORE, MIN_RRF_CANDIDATES,
    )

    return filtered[:top_k]


if __name__ == "__main__":
    # smoke test — compare hybrid vs semantic side by side
    from retrieval.semantic import semantic_search

    sample_query = "What controls govern access management in federal systems?"

    print(f"\nQuery: {sample_query}\n")
    print("=" * 60)
    print("HYBRID (dense + sparse + RRF)")
    print("=" * 60)
    for i, r in enumerate(hybrid_search(sample_query, top_k=5), 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()

    print("=" * 60)
    print("SEMANTIC ONLY (dense)")
    print("=" * 60)
    for i, r in enumerate(semantic_search(sample_query, top_k=5), 1):
        print(f"[{i}] score={r['score']}  source={r['source']}  page={r['page']}")
        print(f"     {r['text'][:200].strip()}")
        print()
