import streamlit as st

from pipeline import run_pipeline

# --- page config ---
st.set_page_config(
    page_title="Governed Compliance Assistant",
    page_icon="🏛️",
    layout="wide",
)

# --- sidebar ---
with st.sidebar:
    st.title("⚙️ Settings")

    use_hybrid = st.toggle(
        "Hybrid Retrieval",
        value=True,
        help="ON: dense + sparse + RRF fusion. OFF: semantic (dense) only.",
    )

    st.divider()
    st.markdown("**Corpus**")
    st.markdown(
        "- NIST SP 800-53 Rev 5\n"
        "- NIST AI RMF (AI 100-1)\n"
        "- NIST AI 600-1\n"
        "- FedRAMP Moderate Baseline"
    )

    st.divider()
    st.markdown("**Observability**")
    st.markdown("[Langfuse traces →](https://us.cloud.langfuse.com)")

    st.divider()
    st.caption(
        "Answers are grounded in the corpus above. "
        "Verify critical compliance decisions against primary sources."
    )

# --- main ---
st.title("🏛️ Governed Compliance Assistant")
st.caption(
    "Research assistant over NIST 800-53, AI RMF, AI 600-1, and FedRAMP Moderate. "
    "Not an official government tool."
)
st.caption("Hybrid retrieval · Cohere reranking · Claude Sonnet 4.5 · Bedrock Guardrails")

# initialize chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg["role"] == "assistant" and msg.get("sources"):
            with st.expander(f"📄 Sources ({len(msg['sources'])} chunks)"):
                for chunk in msg["sources"]:
                    score = chunk.get("rerank_score", chunk.get("score", 0))
                    st.markdown(
                        f"**{chunk['display_name']}** — page {chunk.get('page', 'N/A')} "
                        f"&nbsp;`score: {score:.4f}`"
                    )
                    st.caption(chunk["text"][:300].strip() + "…")
                    st.divider()

        if msg["role"] == "assistant" and msg.get("metadata"):
            meta = msg["metadata"]
            filter_parts = []
            if meta.get("filters", {}).get("control_family"):
                filter_parts.append(meta["filters"]["control_family"])
            if meta.get("filters", {}).get("impact_level"):
                filter_parts.append(meta["filters"]["impact_level"])
            filter_label = " | ".join(filter_parts) if filter_parts else "none"

            cols = st.columns(4)
            cols[0].caption(f"Retriever: `{meta['retriever']}`")
            cols[1].caption(f"Filter: `{filter_label}`")
            cols[2].caption(f"Guardrail: `{meta['guardrail_action']}`")
            cols[3].caption(f"Trace: `{meta['trace_id']}`")

# chat input
if query := st.chat_input("Ask a compliance question…"):

    # Capture history BEFORE appending current message — enrich_query needs
    # prior turns as context, not the current question being asked.
    history_before = list(st.session_state.messages)

    # render user message
    with st.chat_message("user"):
        st.markdown(query)
    st.session_state.messages.append({"role": "user", "content": query})

    # run pipeline with prior history for query enrichment
    with st.chat_message("assistant"):
        with st.spinner("Retrieving · Reranking · Generating…"):
            try:
                output = run_pipeline(query, use_hybrid=use_hybrid, history=history_before)
            except Exception as e:
                st.error(f"Pipeline error: {e}")
                st.stop()

        st.markdown(output["answer"])

        # enriched query label — shown only when the rewrite actually fired.
        # This is the key demo moment: user sees "that" resolved to "AC-6"
        # before retrieval, confirming conversational context is working.
        if output.get("query_was_enriched"):
            st.caption(f"💬 Query resolved to: *{output['enriched_query']}*")

        # sources expander
        with st.expander(f"📄 Sources ({len(output['chunks'])} chunks)"):
            for chunk in output["chunks"]:
                score = chunk.get("rerank_score", chunk.get("score", 0))
                st.markdown(
                    f"**{chunk['display_name']}** — page {chunk.get('page', 'N/A')} "
                    f"&nbsp;`score: {score:.4f}`"
                )
                st.caption(chunk["text"][:300].strip() + "…")
                st.divider()

        # metadata row — trace_id is None when input guardrail blocks early
        # filters label shows which metadata pre-filter fired (e.g. "AC | Moderate")
        # or "none" when the classifier found no signal and a full-corpus scan ran.
        filter_parts = []
        if output.get("filters", {}).get("control_family"):
            filter_parts.append(output["filters"]["control_family"])
        if output.get("filters", {}).get("impact_level"):
            filter_parts.append(output["filters"]["impact_level"])
        filter_label = " | ".join(filter_parts) if filter_parts else "none"

        cols = st.columns(4)
        cols[0].caption(f"Retriever: `{output['retriever']}`")
        cols[1].caption(f"Filter: `{filter_label}`")
        cols[2].caption(f"Guardrail: `{output['guardrail_action']}`")
        trace_label = output["trace_id"] if output["trace_id"] else "blocked"
        cols[3].caption(f"Trace: `{trace_label}`")

    # save to session state
    st.session_state.messages.append({
        "role": "assistant",
        "content": output["answer"],
        "sources": output["chunks"],
        "metadata": {
            "retriever": "hybrid" if use_hybrid else "semantic",
            "filters": output.get("filters", {}),
            "guardrail_action": output["guardrail_action"],
            "trace_id": output["trace_id"],
            # enrichment fields persisted for history replay and debugging
            "enriched_query": output.get("enriched_query", ""),
            "query_was_enriched": output.get("query_was_enriched", False),
        },
    })
