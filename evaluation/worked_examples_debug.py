"""Debug helpers — print formatted RETRIEVE/RERANK/SUMMARY blocks for worked examples.

Used by run_pipeline() in pipeline.py when DEBUG_PIPELINE=true is set in the environment.
Output is formatted to match the table style in README.md "Worked Examples" section, so
output can be pasted directly into documentation when regenerating worked examples after
pipeline or corpus changes.

Driver: scripts/run_worked_examples.py runs the full set of MAIN-1..3 and NEG-1..3 queries
and produces one set of blocks per query.

When DEBUG_PIPELINE is unset, none of these helpers are imported — pipeline.py guards
each call site with `if _DEBUG:`.

see docs/decision_log.md DL-029
"""

_RULE = "=" * 72
_DASH = "-" * 72


def print_enrichment_block(
    original: str,
    enriched: str,
    fired: bool,
    guardrail_action: str,
) -> None:
    print(f"\n{_RULE}")
    print("QUERY ENRICHMENT")
    print(f"  original : {original!r}")
    print(f"  enriched : {enriched!r}")
    print(f"  fired    : {fired}")
    print(f"  guardrail input: {guardrail_action}")


def print_retrieve_block(chunks: list, filters: dict) -> None:
    """Print the post-RRF candidate table with control_family looked up from DB.

    The control_family field is not always present on the chunk dict returned by
    hybrid_search/semantic_search (depends on join shape), so a single batched
    SELECT recovers it for display. BM25 fired heuristic uses RRF score > 0.025
    as a proxy for "this chunk was elevated by the BM25 leg" — pure-dense rank-1
    tops out at 1/(60+1) = 0.0164.
    """
    from retrieval.semantic import get_connection

    ids = [c["chunk_id"] for c in chunks]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT chunk_id, control_family FROM chunks WHERE chunk_id = ANY(%s)",
                (ids,),
            )
            cf_map = {r[0]: (r[1] or "—") for r in cur.fetchall()}
    finally:
        conn.close()

    bm25_fired = any(c.get("score", 0) > 0.025 for c in chunks)
    print(f"\n{_RULE}")
    print(
        f"RETRIEVE — {len(chunks)} candidates | filters={filters} | "
        f"BM25 fired: {bm25_fired}"
    )
    print(_RULE)
    print(f"{'Rk':<4} {'Source':<26} {'CF':<5} {'Score':<10} {'BM25':<5} Content")
    print(_DASH)
    for i, c in enumerate(chunks, 1):
        score = c.get("score", 0)
        bm25 = "Yes" if score > 0.025 else "No"
        cf = cf_map.get(c["chunk_id"], "—")
        preview = c["text"][:80].strip()
        print(
            f"[{i:2d}] {c['source'][:25]:<26} {cf:<5} {score:.6f}  "
            f"{bm25:<5} {preview}"
        )


def print_rerank_block(reranked: list) -> None:
    print(f"\n{_RULE}")
    print(f"RERANK — top {len(reranked)} after Cohere")
    print(_RULE)
    print(f"{'Rk':<4} {'Source':<26} {'Rerank Score':<14} Content")
    print(_DASH)
    for i, c in enumerate(reranked, 1):
        rs = c.get("rerank_score", c.get("score", 0))
        preview = c["text"][:80].strip()
        print(f"[{i}]  {c['source'][:25]:<26} {rs:<14.6f} {preview}")


def print_summary_block(
    filters: dict,
    query_was_enriched: bool,
    guardrail_input: str,
    guardrail_output: str,
    trace_id: str,
    elapsed_ms: int,
    answer: str,
) -> None:
    print(f"\n{_RULE}")
    print("PIPELINE SUMMARY")
    print(_RULE)
    print(f"  filters          : {filters}")
    print(f"  query enriched   : {query_was_enriched}")
    print(f"  guardrail input  : {guardrail_input}")
    print(f"  guardrail output : {guardrail_output}")
    print(f"  trace ID         : {trace_id}")
    print(f"  total latency    : {elapsed_ms}ms")
    print(f"\nANSWER:\n{answer}")
    print(_RULE)
