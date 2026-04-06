# governed-compliance-engine
## Production-Grade Governed RAG System — Federal Compliance Intelligence

**Raghunath Devayajanam**
GitHub: https://github.com/ai-systems-architect/governed-compliance-engine

---

## What This Is

A production-grade Retrieval-Augmented Generation pipeline over federal
compliance documents — NIST SP 800-53 Rev 5, NIST AI RMF 1.0, NIST AI
600-1, and FedRAMP Moderate Baseline. The system answers compliance
questions by retrieving authoritative source content, reranking for
precision, generating grounded responses via Claude Sonnet 4.5 through
Amazon Bedrock, and enforcing guardrails against overclaiming.

Built as a compliance reference assistant — not a compliance assessment
tool. The system retrieves and synthesizes what the frameworks require.
It does not assess whether a specific system satisfies those requirements.
That distinction is enforced in the system prompt and validated by
Bedrock Guardrails on every response.

---

## Why This Corpus

Federal compliance work is document-intensive and terminology-precise.
A compliance engineer asking about access control requirements needs
answers grounded in the actual control text — not model weights trained
on internet data that may be outdated or imprecise.

Four authoritative documents were selected to cover the full federal AI
compliance stack: NIST 800-53 for security controls, AI RMF for AI risk
governance, AI 600-1 for GenAI-specific risk, and FedRAMP Moderate for
cloud authorization requirements. Together they represent the primary
frameworks a federal AI system must navigate from design through ATO.

---

## Pipeline Architecture

```
Query → Embed → Hybrid Retrieval (top-10) → Cohere Rerank (top-5)
      → Bedrock Guardrails → Claude Sonnet 4.5 → Answer
      → Langfuse Trace (retrieve / rerank / generate spans)
      → Streamlit UI (answer + source citations + metadata)
```

Each stage is a standalone module. The `use_hybrid` flag in `pipeline.py`
switches between semantic-only and hybrid retrieval without touching any
other component — both retrievers return identical output shape.

**Ingestion layer**
- `ingestion/download.py` — downloads corpus PDFs, converts FedRAMP .docx
  to PDF via LibreOffice headless, uploads to S3
- `ingestion/parse.py` — PyMuPDF text extraction per page
- `ingestion/chunk.py` — tiktoken cl100k_base chunking, 600 tokens /
  100 overlap, saves chunks.json
- `ingestion/embed.py` — OpenAI text-embedding-3-large batch embedding,
  idempotent upsert to RDS

**Retrieval layer**
- `retrieval/semantic.py` — pgvector HNSW cosine search, top-10
- `retrieval/hybrid.py` — dense + tsvector BM25 fused via RRF (k=60), top-10
- `retrieval/rerank.py` — Cohere rerank-english-v3.0 cross-encoder, top-10 → top-5

**Generation layer**
- `generation/generate.py` — Claude Sonnet 4.5 via Bedrock converse API,
  Guardrails conditional on BEDROCK_GUARDRAIL_ID

**Observability layer**
- `tracing/tracer.py` — Langfuse Cloud client, span per pipeline stage

**Evaluation layer**
- `evaluation/golden_dataset.json` — 20 architect-level questions with
  reference answers across all four corpus sources
- `evaluation/ragas_eval.py` — RAGAs evaluation, semantic vs hybrid
  comparison, results saved to data/ragas_results.json

**Orchestration and UI**
- `pipeline.py` — full orchestrator with Langfuse instrumentation
- `app.py` — Streamlit chat interface with hybrid toggle, source citations,
  guardrail action display, trace ID per response

---

## Why This Is More Than Simple RAG

Most RAG implementations stop at embed → retrieve → generate. Every
additional layer here exists because of a specific production failure mode.

| Layer | Why it exists |
|-------|---------------|
| Hybrid retrieval — dense + BM25 + RRF | Keyword queries fail pure semantic search — control identifiers like AC-6 and IR-4 are high-value BM25 targets |
| Cohere cross-encoder reranking | Bi-encoder similarity has a precision ceiling — cross-encoder sees query and chunk together, producing a trained relevance judgment |
| Bedrock Guardrails | Overclaiming risk is high in federal compliance context — a system that asserts authorization status is a liability |
| Langfuse Cloud tracing | Cannot debug or improve what cannot be observed — every retrieval, rerank, and generation call traced end-to-end |
| RAGAs evaluation against golden dataset | Quantified retrieval quality, not subjective assessment — semantic vs hybrid comparison produces a defensible result |
| Provider abstraction layer | Embedding and generation models swappable via environment variables without pipeline rewrites |
| Single AWS boundary | Query, retrieved chunks, and generated response never leave AWS — Bedrock for generation, RDS for vector store, S3 for corpus |

---

## Retrieval Architecture — Why Hybrid

**Dense retrieval (pgvector HNSW)** embeds the query and chunks
independently then measures cosine similarity between vectors. Fast
and effective for conceptual and abstract queries — AI RMF governance
language, risk framework concepts, cross-corpus synthesis questions.

**Sparse retrieval (tsvector BM25)** matches on vocabulary. Effective
for queries containing exact control identifiers — AC-6, IR-4, SC-28,
CM-7. A compliance engineer searching for a specific control by ID gets
the right chunks surfaced immediately.

**RRF fusion (k=60)** combines both ranked lists using Reciprocal Rank
Fusion: score = Σ 1/(60 + rank). The constant k=60 is empirically
validated across information retrieval literature — it prevents
high-ranked results from dominating while preserving rank signal.

**BM25 query preprocessing:** Long natural language questions AND-chain
all terms via plainto_tsquery, returning zero results when no single
chunk contains every term simultaneously. Preprocessing strips stop words
and limits to five key terms before passing to BM25. Known limitation:
control identifiers (AC-6, IR-4) may be dropped if they fall after the
five-term limit — regex pre-extraction of control IDs is a documented
future enhancement (see docs/decision_log.md DL-019).

**Cohere reranking:** The cross-encoder reads query and chunk together —
joint inference via attention mechanism — producing a relevance probability
rather than a geometric distance. Runs only on the top-10 retrieved chunks,
not the full corpus, keeping cost negligible.

---

## RAGAs Evaluation Results

Evaluated against a 20-question golden dataset — five questions per
corpus source, three cross-corpus synthesis questions requiring reasoning
across multiple documents.

| Metric | Semantic | Hybrid | Target | Status |
|--------|----------|--------|--------|--------|
| Faithfulness | 0.90 | 0.89 | 0.75 min | Exceeds target |
| Answer Relevancy | 0.56 | 0.51 | 0.70 min | Below target — documented |
| Context Precision | 0.94 | 0.95 | 0.65 min | Exceeds stretch target |
| Context Recall | 0.75 | 0.76 | 0.60 min | Meets good threshold |

**Faithfulness 0.90** — generated answers are grounded in retrieved
chunks. The system is not fabricating control requirements or
hallucinating NIST citations. Most critical metric for federal compliance
use — stable across both retrievers and both evaluation runs.

**Context Precision 0.94** — the right chunks rank at the top before
generation. Cohere reranking is demoting geometrically-close but
topically-adjacent chunks in favor of directly relevant content.

**Hybrid vs semantic:** Hybrid wins context precision (+0.01) and
context recall (+0.01), confirming BM25 adds signal for keyword-dominant
NIST 800-53 and FedRAMP queries. BM25 fired on 10 of 20 questions —
AI RMF and AI 600-1 governance language is too diffuse for BM25 to
anchor on, so hybrid falls back to dense-only for those queries.

**Answer relevancy 0.55** is below the 0.70 minimum. Two documented
causes: the system prompt instructs Claude to hedge and note applicability
limitations — correct for compliance but penalized by this metric. And
architect-level multi-part questions fragment RAGAs synthetic question
comparison. Faithfulness and context precision are the more reliable
quality signals for this use case. Answer relevancy was not tuned —
optimizing for it would require weakening compliance safety behavior or
simplifying the evaluation questions, both of which reduce system
integrity and evaluation validity.

---

## Key Architectural Decisions

Full rationale with alternatives evaluated in `docs/decision_log.md`
(DL-001 through DL-020).

| Decision | Choice | Key rationale |
|----------|--------|---------------|
| Embedding model | OpenAI text-embedding-3-large at 1536 dims | Highest quality for dense regulatory text. Matryoshka truncation from 3072 — pgvector HNSW has 2000-dim ceiling |
| Vector store | pgvector on RDS | Single AWS boundary. HNSW sufficient at <100K chunks |
| Generation | Claude Sonnet 4.5 via Bedrock | Stays in AWS boundary. Direct Anthropic API would send chunks outside AWS |
| Reranking | Cohere rerank-english-v3.0 | Cross-encoder precision over bi-encoder on regulatory text |
| Tracing | Langfuse Cloud | Full pipeline observability — LANGFUSE_HOST in config controls self-hosted vs Cloud |
| Chunking | 600 tokens / 100 overlap, tiktoken | Preserves full control statements. Character count would split mid-sentence |
| Retrieval fusion | RRF k=60 | Standard IR constant — empirically validated, prevents rank dominance |
| BM25 query | plainto_tsquery with 5-term limit | Handles natural language safely. to_tsquery throws on unprocessed input |
| Production ingestion | AWS Batch recommended | Ephemeral containers, pay-per-runtime, right fit for periodic pipeline |

---

## NIST AI RMF Alignment

| Function | Implementation |
|---|---|
| GOVERN | System prompt enforces compliance reference boundary — no overclaiming, Bedrock Guardrails enforcement, decision log documents all architectural choices |
| MAP | Corpus scope explicitly bounded to four frameworks, system capability ceiling documented in README, PII surfaces identified across input / corpus / output / traces |
| MEASURE | RAGAs evaluation against 20-question golden dataset, semantic vs hybrid quantified comparison, Langfuse latency and span tracing per pipeline stage |
| MANAGE | Guardrails block overclaiming responses, provider abstraction enables model swap without pipeline rewrite, AWS Batch recommended for production ingestion |

---

## Infrastructure

All AWS resources provisioned via Terraform. RDS stopped by default
between ingestion runs — `scripts/rds_start.py` and `scripts/rds_stop.py`
manage lifecycle to minimize cost.

Resources provisioned:
- RDS PostgreSQL 15 — pgvector extension, HNSW cosine index, GIN
  tsvector index, SSL enforced (rds.force_ssl=1)
- S3 corpus bucket — raw/ and processed/ prefixes, public access blocked
- IAM roles — least privilege, Bedrock and S3 access scoped to pipeline

Streamlit UI deployed to Streamlit Community Cloud (GCP). RDS public
endpoint with SSL enforced — required for Streamlit on GCP to reach
RDS in AWS default VPC.

---

## Tech Stack

Python 3.11 | OpenAI text-embedding-3-large | Claude Sonnet 4.5 via
Amazon Bedrock | pgvector on RDS PostgreSQL 15 | Cohere rerank-english-v3.0 |
LangChain | Langfuse Cloud | RAGAs | Streamlit Community Cloud |
PyMuPDF | tiktoken | Terraform

---

## Corpus

| Document | Source | Chunks |
|----------|--------|--------|
| NIST SP 800-53 Rev 5 | NIST | 1,112 |
| NIST AI RMF 1.0 | NIST | 50 |
| NIST AI 600-1 | NIST | 92 |
| FedRAMP Moderate Baseline | FedRAMP | 442 |
| **Total** | | **1,696** |

---

## Future Work

**System profile intake** — structured intake of system impact level,
deployment model, and data types to condition retrieval. Enables
control applicability answers specific to a target system rather than
general corpus lookup.

**Control checklist generation** — second LLM call post-retrieval to
structure answers as actionable, system-specific control checklists
rather than prose summaries.

**PII filtering** — production deployment requires PII detection and
redaction at query input, corpus ingestion, and generated output.
Microsoft Presidio or AWS Comprehend recommended. Langfuse traces
should be scrubbed at source to prevent PII persistence.

**Metadata filtering** — pre-filtering chunks by source document or
impact level before vector search, recommended as corpus expands
beyond four documents. Pairs with system profile intake.

**Retrieval-side conversational memory** — conversation history
currently passed to generation only. Prior turns should condition
the retrieval query — a user who asked about AC-6 then asks "what
about logging requirements" should retrieve AU controls relevant to
access control logging, not generic AU chunks.

---

*Single AWS boundary. Langfuse Cloud observability. RAGAs evaluated.
Bedrock Guardrails enforced. NIST AI RMF aligned.*
