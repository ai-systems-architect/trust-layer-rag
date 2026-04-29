# The Trust Layer for Federal Compliance AI

**Production-grade governed RAG system for federal compliance corpora**

Raghunath Devayajanam · April 2026

📄 **Companion artifacts**

- **[AI Impact Assessment (PDF)](docs/AIIA_FCIS_v1_0.pdf)** — federal-grade governance artifact mapping RAG risks to implemented controls per NIST AI RMF 1.0. Sample artifact — fictional sponsoring agency.
- **Beyond Retrieval: Architecting the Trust Layer for Enterprise AI** *(companion article — link coming May 2026)* — generalized architectural patterns drawn from production RAG governance lessons.

---

## What This Is

A production-grade Retrieval-Augmented Generation pipeline over federal compliance documents — NIST SP 800-53 Rev 5, NIST AI RMF 1.0, NIST AI 600-1, and FedRAMP Moderate Baseline. The system answers compliance questions by retrieving authoritative source content, reranking for precision, generating grounded responses via Claude Sonnet 4.5 through Amazon Bedrock, and enforcing guardrails against unsupported claims.

Built as a compliance *reference assistant* — not a compliance *assessment tool*. The system retrieves and synthesizes what the frameworks require. It does not assess whether a specific system satisfies those requirements. That distinction is enforced in the system prompt and validated by Bedrock Guardrails on every response.

![Governed RAG architecture](docs/images/governed_rag_architecture.png)
*Governed RAG architecture — three-pipeline view with governance, observability, and security boundaries marked.*

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

## Example Capabilities

- Retrieve and explain specific NIST 800-53 controls by ID —
  e.g. "What does AC-6 require and what are its key enhancements?"
- Map AI RMF governance functions to implementation practices —
  e.g. "What does the GOVERN function require of senior leadership?"
- Detect and refuse out-of-scope queries — e.g. quantum cryptography,
  blockchain, and cryptocurrency queries declined via corpus grounding,
  not guardrails

---

## Pipeline Architecture

```
Query → PII Scrub (Presidio) → Input Guardrail (Bedrock) → Query Enrichment
      → Metadata-Filtered Hybrid Retrieval (top-10) → Post-RRF Quality Gate
      → Cohere Rerank (top-5) → Claude Sonnet 4.5 (Bedrock) → Output Guardrail
      → PII Scrub (output) → Answer
      → Langfuse Trace (retrieve / rerank / generate spans)
      → Streamlit UI (answer + enriched query label + source citations + metadata)
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
- `retrieval/semantic.py` — pgvector HNSW cosine search, top-10, metadata pre-filter support
- `retrieval/hybrid.py` — dense + tsvector BM25 fused via RRF (k=60), top-10, post-RRF quality gate (MIN_RRF_SCORE=0.0150)
- `retrieval/query_enrichment.py` — rewrites ambiguous follow-up queries via Bedrock Claude at temperature=0.0
- `retrieval/rerank.py` — Cohere rerank-english-v3.0 cross-encoder, top-10 → top-5

**Generation layer**
- `generation/generate.py` — Claude Sonnet 4.5 via Bedrock converse API,
  dual guardrails (input gate + output guardrailConfig), Pydantic response validation

**Observability layer**
- `tracing/tracer.py` — Langfuse Cloud client, span per pipeline stage

**Evaluation layer**
- `evaluation/golden_dataset.json` — 20 architect-level questions with
  reference answers across all four corpus sources
- `evaluation/ragas_eval.py` — RAGAs evaluation, semantic vs hybrid
  comparison, results saved to data/ragas_results.json
- `evaluation/guardrail_test.py` — adversarial evaluation against five
  negative test cases; two-signal pass detection (hard guardrail block
  or hedge phrase in generated answer)

**Pipeline and UI**
- `pipeline.py` — full orchestrator: PII scrub → input guardrail → query enrichment → classify → retrieve → rerank → generate
- `utils/pii_filter.py` — Presidio scrub at query input and generated output
- `app.py` — Streamlit chat interface with hybrid toggle, enriched query label, source citations, filter label, guardrail action, trace ID per response

---

## Why This Is More Than Simple RAG

Most RAG implementations stop at embed → retrieve → generate. Every
additional layer here exists because of a specific production failure mode.

| Layer | Why it exists |
|-------|---------------|
| PII scrub (Presidio) at input and output | Query text and generated answers scrubbed before any external service call — embedding, reranking, and Langfuse traces receive clean content |
| Input guardrail (Bedrock) before retrieval | Blocks prompt injection and off-topic queries before pgvector, Cohere, or Claude are invoked — one Bedrock call cost vs full pipeline |
| Query enrichment via Bedrock Claude | Pronoun follow-ups ("how does that relate to…") resolved before embedding — retriever embeds a fully specified query, not an unresolved reference |
| Metadata-filtered retrieval (control_family, impact_level) | Rule-based classifier pre-filters the vector search to the relevant NIST family or FedRAMP baseline — reduces noise before RRF fusion |
| Post-RRF quality gate | RRF ranks weak candidates against each other regardless of absolute score — gate (MIN_RRF_SCORE=0.0150) stops noise reaching Cohere |
| Hybrid retrieval — dense + BM25 + RRF | Keyword queries fail pure semantic search — control identifiers like AC-6 and IR-4 are high-value BM25 targets |
| Cohere cross-encoder reranking | Bi-encoder similarity has a precision ceiling — cross-encoder sees query and chunk together, producing a trained relevance judgment |
| Bedrock Guardrails (dual — input + output) | Compliance assertion risk is high in federal contexts — input gate blocks before retrieval fires, output gate catches compliance determinations in generated responses |
| Langfuse Cloud tracing | Cannot debug or improve what cannot be observed — every retrieval, rerank, and generation call traced end-to-end |
| RAGAs evaluation against golden dataset | Quantified retrieval quality, not subjective assessment — semantic vs hybrid comparison produces a defensible result |
| Provider abstraction layer | Embedding and generation models swappable via environment variables without pipeline rewrites |
| AWS boundary for corpus and generation | Corpus vectors remain in AWS (RDS pgvector + S3). Query text to OpenAI for embedding. Chunks to Cohere for reranking. Traces to Langfuse Cloud. Generation stays within AWS via Bedrock |

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
and limits to five key terms before passing to BM25. Control identifiers
(AC-6, IR-4) are regex-extracted from the original query before the
five-term limit applies — they always occupy the leading slots as
high-value BM25 anchors (see docs/decision_log.md DL-019).

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
(DL-001 through DL-029).

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
| GOVERN | System prompt enforces compliance reference boundary — no compliance determinations, output grounded in retrieved context, Bedrock Guardrails enforcement, decision log documents all architectural choices |
| MAP | Corpus scope explicitly bounded to four frameworks, system capability ceiling documented in README, PII surfaces identified across input / corpus / output / traces |
| MEASURE | RAGAs evaluation against 20-question golden dataset, semantic vs hybrid quantified comparison, Langfuse latency and span tracing per pipeline stage |
| MANAGE | Guardrails block compliance determination responses, provider abstraction enables model swap without pipeline rewrite |

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

Implemented items removed — see docs/decision_log.md for closed decisions (DL-001 through DL-029).

### Production Required

**Presidio production path** — PII filtering is implemented at query input and generated output; Langfuse traces receive pre-scrubbed content. Corpus ingestion scrubbing hook exists in `utils/pii_filter.py` but is not wired into the ingestion pipeline — deferred because the current corpus (public NIST documents) contains no PII. Required when corpus expands to SSPs or assessment reports. AWS Comprehend is the recommended managed replacement for Presidio in a full production AWS deployment. See docs/decision_log.md DL-017.

**RAG-RBAC role-based retrieval filtering** — `sensitivity_level` column in chunks table with `WHERE sensitivity_level <= user_clearance` pre-filter. Foundation already exists in the metadata filtering layer (DL-023). Required when corpus includes controlled or sensitivity-tiered documents.

### Stretch

**Evaluation depth — entity-level recall and citation verification** — two complementary additions to the current evaluation framework. *Context entities recall:* RAGAs metric that checks whether specific identifiers from the reference answer (AC-2, MAP-1.1) appear inside retrieved chunk text. Complementary to Recall@k — Recall@k confirms the right chunk IDs were retrieved, entity recall confirms those chunks actually contain the control identifiers the answer needs. *Citation precision automation:* citations are enforced at generation time; automation cross-references each generated citation against source PDF section/page to catch cases where the model cites a plausible but incorrect section. Currently spot-checked manually per worked example; automation scales verification to all 20 golden dataset questions.

**System-specific compliance assistant** — per-session intake of system impact level, deployment model, and data types to condition retrieval; structured checklist generation as a second LLM call post-retrieval to produce system-specific control checklists rather than prose; cross-session profile persistence in RDS keyed by user ID. Three phases of one capability — moves the system from general corpus lookup toward target-system control applicability. Within-session memory already implemented via DL-025.

**Structured intent extraction** — classify query intent (control lookup, gap assessment, cross-framework synthesis) before retrieval. Route to appropriate retriever config per intent — control ID lookup favors BM25 (evidence in retrieval diagnostics by query type); other intents may benefit from different retriever configurations, to be validated empirically.

**True AWS-boundary variant** — replace OpenAI embeddings with Amazon Titan or Cohere Embed via Bedrock to keep all data within the AWS boundary at ingestion time.

**Query expansion / multi-query rewriting** — HyDE or LLM-generated query variants to broaden retrieval on abstract governance queries where vocabulary mismatch causes semantic drift.

### Considered and Deferred

**Self-correction loop** — re-attempt retrieval with broader search radius when faithfulness scores fall below threshold. Evaluated and deferred for this system: the dual-guardrail design provides the safety floor, and the re-attempt pattern is more appropriate for production agentic systems where retrieval-time decisions feed into multi-step workflows. Reconsider when this codebase extends to agentic patterns.

---

*Generation and vector store within AWS boundary. RAGAs evaluated. Dual Bedrock Guardrails
enforced. PII filtered at input and output. GCP and Azure equivalents documented.
Architectural controls mapped to NIST AI RMF 1.0 functions — see "NIST AI RMF Alignment" section above. Decision rationale: DL-001 through DL-029.*
