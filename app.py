import streamlit as st

from pipeline import run_pipeline

# --- page config ---
st.set_page_config(
    page_title="Federal Compliance Assistant",
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
    st.markdown("[Langfuse traces →](http://localhost:3000)")

    st.divider()
    st.caption(
        "Answers are grounded in the corpus above. "
        "Verify critical compliance decisions against primary sources."
    )

# --- main ---
st.title("🏛️ Federal Compliance Assistant")
st.caption(
    "RAG pipeline over NIST 800-53, AI RMF, AI 600-1, and FedRAMP Moderate. "
    "Hybrid retrieval · Cohere reranking · Claude 3.5 Sonnet · Bedrock Guardrails."
)

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
            cols = st.columns(3)
            cols[0].caption(f"Retriever: `{meta['retriever']}`")
            cols[1].caption(f"Guardrail: `{meta['guardrail_action']}`")
            cols[2].caption(f"Trace: `{meta['trace_id']}`")

# chat input
if query := st.chat_input("Ask a compliance question…"):

    # render user message
    with st.chat_message("user"):
        st.markdown(query)
    st.session_state.messages.append({"role": "user", "content": query})

    # run pipeline
    with st.chat_message("assistant"):
        with st.spinner("Retrieving · Reranking · Generating…"):
            try:
                output = run_pipeline(query, use_hybrid=use_hybrid)
            except Exception as e:
                st.error(f"Pipeline error: {e}")
                st.stop()

        st.markdown(output["answer"])

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

        # metadata row
        cols = st.columns(3)
        cols[0].caption(f"Retriever: `{'hybrid' if use_hybrid else 'semantic'}`")
        cols[1].caption(f"Guardrail: `{output['guardrail_action']}`")
        cols[2].caption(f"Trace: `{output['trace_id']}`")

    # save to session state
    st.session_state.messages.append({
        "role": "assistant",
        "content": output["answer"],
        "sources": output["chunks"],
        "metadata": {
            "retriever": "hybrid" if use_hybrid else "semantic",
            "guardrail_action": output["guardrail_action"],
            "trace_id": output["trace_id"],
        },
    })
