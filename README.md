# governed-compliance-engine

Governed RAG system for NIST, FISMA, and FedRAMP compliance — hybrid retrieval,
hallucination controls, and full pipeline observability.

**Portfolio:** P2 of 4 — follows [responsible-mlops-risk-engine](https://github.com/ai-systems-architect/responsible-mlops-risk-engine)

---

## Architecture

| Layer | Component | Tool |
|---|---|---|
| Ingestion | PDF + Word parsing, chunking | LibreOffice headless (.docx → PDF conversion) + PyMuPDF |
| Embedding | Dense vectors (1536 dims) | OpenAI text-embedding-3-large |
| Vector Store | pgvector + HNSW index | RDS PostgreSQL |
| Retrieval | Dense + sparse fused via RRF | pgvector + tsvector |
| Re-ranking | Cross-encoder re-rank | Cohere rerank-english-v3.0 |
| Tracing | Full pipeline observability | Langfuse Cloud |
| Generation | Citation-enforced prompts | Claude Sonnet 4.5 via Bedrock |
| Guardrails | PII + hallucination controls | Bedrock Guardrails |
| Evaluation | Golden dataset scoring | RAGAs |
| Frontend | Chat UI + debug sidebar | Streamlit |
| Infrastructure | RDS, S3, IAM | Terraform + AWS |

Full rationale for each component: [docs/decision_log.md](docs/decision_log.md)
Cloud equivalents (GCP, Azure): [docs/architecture.md](docs/architecture.md)

---

## Why More Than Basic RAG

Most RAG implementations stop at embed → retrieve → generate.
This pipeline adds production layers motivated by real failure modes:

| Addition | Why it exists |
|----------|---------------|
| Hybrid retrieval (dense + BM25 + RRF) | Keyword queries fail pure semantic search |
| Cohere reranking | Bi-encoder similarity has a precision ceiling |
| Bedrock Guardrails | Overclaiming risk is high in federal compliance context |
| Langfuse tracing | Can't debug or improve what you can't observe |
| RAGAs evaluation | Quantified retrieval quality against a golden dataset |
| Provider abstraction layer | Model swappability without pipeline rewrites |

---

## Evaluation Results

RAGAs evaluation against a 20-question golden dataset covering all
four corpus sources including cross-corpus synthesis questions.

| Metric | Semantic | Hybrid |
|--------|----------|--------|
| Faithfulness | 0.90 | 0.89 |
| Answer Relevancy | 0.56 | 0.51 |
| Context Precision | 0.94 | 0.95 |
| Context Recall | 0.75 | 0.76 |

Hybrid retrieval outperforms semantic on context precision, confirming
BM25 adds signal for keyword-dominant NIST 800-53 and FedRAMP queries
containing exact control identifiers. For AI RMF and AI 600-1 governance
queries, dense retrieval is sufficient — governance language does not
produce distinctive BM25 tokens.

Answer relevancy scores lower than other metrics for two reasons: the
system prompt instructs Claude to hedge and note applicability limitations
rather than answer directly — correct behavior for federal compliance but
penalized by this metric. Additionally, architect-level multi-part
questions fragment RAGAs synthetic question comparison. Faithfulness
(0.90) and context precision (0.94) are the primary quality signals
for this use case.

### Retrieval Diagnostics

Retrieval quality measured independently of generation — Recall@5, MRR,
and nDCG across three pipeline configurations. Ground truth labels derived
from token overlap with reference answers across a broad candidate pool.

| Query Type | R@5 Semantic | R@5 Hybrid | R@5 H+Rerank | MRR Semantic | MRR Hybrid | MRR H+Rerank |
|---|---|---|---|---|---|---|
| Control ID (n=9) | 0.1516 | 0.1558 | 0.1558 | 1.0000 | 1.0000 | 1.0000 |
| Governance (n=8) | 0.2099 | 0.2099 | 0.2197 | 0.8750 | 0.9375 | 0.9375 |
| Cross-corpus (n=3) | 0.1130 | 0.1258 | 0.1258 | 0.6667 | 0.6667 | 0.6667 |
| **Average (n=20)** | **0.1691** | **0.1729** | **0.1768** | **0.9000** | **0.9250** | **0.9250** |

nDCG@5 — Semantic: 0.888 | Hybrid: 0.909 | Hybrid+Rerank: 0.927

The most relevant chunk surfaces at rank 1 for 90%+ of questions (MRR 0.90+).
Recall@5 appears low (0.17) because the ground truth pool averages 28 chunks
per question — top-5 retrieval capturing 17% of 28 labeled chunks reflects the
large denominator, not a retrieval failure. nDCG@5 progression (0.888 → 0.909
→ 0.927) confirms each pipeline layer adds ranking quality: RRF fusion improves
governance query ranking (MRR 0.875 → 0.938), Cohere cross-encoder refines
mid-list precision without displacing already-correct top-1 positions (MRR
unchanged at Hybrid → H+Rerank, nDCG +0.018). Control ID queries achieve
perfect MRR 1.00 across all configurations — exact control identifiers anchor
both dense and BM25 retrieval reliably.

---

## Corpus

Four authoritative federal sources — no synthetic data.

| Source | Format | Chunks | Purpose |
|---|---|---|---|
| NIST SP 800-53 Rev 5 | PDF | 1,112 | Master federal security control catalog |
| NIST AI RMF 1.0 | PDF | 50 | AI risk management — bridges to P1 portfolio project |
| NIST AI 600-1 GenAI Profile | PDF | 92 | AI-specific risk and trustworthiness guidance |
| FedRAMP Moderate Baseline | Word | 442 | Maps 800-53 controls to cloud authorization requirements |

Total: 1,696 chunks — one-time ingestion cost ~$0.07 (OpenAI embeddings)

---

## Pipeline

Queries flow through five stages:

**Ingestion** — NIST 800-53, AI RMF, AI 600-1, and FedRAMP Moderate
documents parsed, chunked, embedded, and stored in pgvector on RDS.

**Retrieval** — Hybrid dense (pgvector HNSW) + sparse (BM25 tsvector)
search fused via Reciprocal Rank Fusion. Returns top-10 chunks.

**Reranking** — Cohere rerank-english-v3.0 cross-encoder scores all
10 chunks jointly against the query. Returns top-5.

**Generation** — Claude Sonnet 4.5 via Amazon Bedrock with Guardrails
applied to prevent overclaiming on compliance topics.

**Evaluation** — RAGAs evaluation against a 20-question golden dataset
covering all four corpus sources including cross-corpus synthesis questions.

---

## System Dependencies

LibreOffice is required for FedRAMP document conversion:

```bash
# Mac
brew install libreoffice

# Ubuntu / EC2
sudo apt-get install libreoffice
```

---

## Setup

```bash
git clone https://github.com/ai-systems-architect/governed-compliance-engine.git
cd governed-compliance-engine
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in .env with your credentials
export PYTHONPATH=.
```

**Requirements:**
- Python 3.9+
- LibreOffice (FedRAMP .docx → PDF conversion)
- AWS CLI configured with Bedrock access
- OpenAI API key
- Cohere API key
- Langfuse account (Cloud — us.cloud.langfuse.com)
- PostgreSQL RDS instance with pgvector extension (provisioned via Terraform in Step 1)

---

## RAGAs Score Progression

| Pipeline Stage | Faithfulness | Context Precision | Context Recall | Answer Relevancy |
|---|---|---|---|---|
| Dense-only (semantic) baseline | 0.90 | 0.94 | 0.75 | 0.56 |
| Hybrid retrieval (RRF + BM25) | 0.89 | 0.95 | 0.76 | 0.51 |

---

## Pipeline Latency and Cost Per Query

| Stage | Typical Latency | Notes |
|---|---|---|
| Embed query | ~50–100ms | OpenAI API |
| Dense retrieval | ~20–50ms | pgvector HNSW |
| Sparse retrieval | ~10–30ms | PostgreSQL tsvector |
| Rerank | ~200–400ms | Cohere API — dominant latency |
| Generation | ~1000–3000ms | Bedrock Claude Sonnet |
| **Total end-to-end** | **~1.5–4s** | |

| Component | Cost Per Query |
|---|---|
| OpenAI embedding | ~$0.00013 |
| Cohere rerank | ~$0.001 |
| Bedrock Claude Sonnet | ~$0.003–0.015 (varies by output length) |
| **Approximate total** | **~$0.004–0.016** |

Langfuse traces confirm these ranges. Reranking is the dominant latency stage —
Cohere API round-trip accounts for ~30–50% of total query time.

---

## Cost

| Component | Cost |
|---|---|
| One-time ingestion (OpenAI embeddings) | ~$0.07 |
| Development (RDS + Bedrock + Cohere) | ~$15–30 total |
| Live demo (RDS t3.micro + Bedrock per query) | ~$17–20/month |
| Langfuse, Streamlit Community Cloud | $0 |

RDS is provisioned on demand — tear down when not actively building (~$2/day active).

---

## Future Work

**[Stretch] System profile intake** — structured intake of system impact level, deployment
model, and data types to condition retrieval. Enables control applicability answers
specific to a target system rather than general corpus lookup.

**[Stretch] Control checklist generation** — second LLM call post-retrieval to structure
answers as actionable, system-specific control checklists rather than prose summaries.

**[Planned Next] Conversational memory** — short-term session context is implemented in Streamlit:
conversation history (concatenated prior Q+A turns) is passed to Claude at generation
time, so answers are contextually aware within a session.

What is not implemented: conversation history does not influence the retrieval query.
Each query hits pgvector as a standalone question regardless of prior turns. A user
who asked about AC-6 then asks "what about logging requirements" — the retriever
searches only on the second question, not the enriched context. Retrieval-side memory
would inject recent turns into the query before embedding, surfacing chunks relevant
to the full conversation thread rather than the isolated question.

Long-term memory across sessions — persisting user system profile (impact level,
deployment model, control families reviewed) in RDS keyed by user ID — is not
implemented. Would enable the system to answer "given your Moderate-impact SaaS
system, here are the AC controls you still need to address" rather than answering
generically on every session.

Implementation patterns: query enrichment with recent turns for short-term retrieval
memory, vector memory (embed prior interactions, retrieve relevant past context
alongside corpus chunks) for long-term. Pairs with system profile intake future work
item.

**[Production Required] PII filtering** — production deployment requires PII detection and redaction at
query input (before embedding), corpus ingestion (before chunking), and generated
output (before UI rendering). Microsoft Presidio or AWS Comprehend recommended.
Langfuse traces should be scrubbed at source to prevent PII persistence in the
observability store. See docs/decision_log.md DL-017.

**[Planned Next] Metadata filtering** — production deployment would benefit from pre-filtering chunks
by source document, impact level, or control family before vector search. Current
implementation searches the full corpus for every query. As corpus expands —
agency-specific SSPs, additional NIST publications, vendor documentation — unfiltered
search introduces noise from irrelevant documents. Implementation: add source,
impact_level, and control_family metadata columns to the chunks table, filter via SQL
WHERE clause before HNSW search. Pairs naturally with system profile intake — once
the user's system impact level is known, retrieval can be scoped to the relevant
baseline automatically. At current four-document scale, full corpus search is fast and
filtering would reduce recall.

**[Production Required] Query guardrail** — validate and sanitize query input before embedding. Block
prompt injection attempts, extremely long inputs, and non-compliance queries. Bedrock
Guardrails currently applied at generation output only — input-side validation is a
separate enforcement layer.

**[Stretch] Structured intent extraction** — classify query intent (control lookup, gap
assessment, cross-framework synthesis) before retrieval. Route to appropriate retriever
config per intent — control lookup favors BM25, synthesis favors dense.

**[Stretch] Context entities recall** — RAGAs entity-level retrieval metric to verify key
identifiers such as MAP-1.1 or AC-2 are not dropped during retrieval. Defer until
Recall@k and MRR baselines are established — entity recall is a refinement on standard
retrieval diagnostics, not a replacement.

**[Planned Next] Post-RRF filter enforcement** — after RRF fusion, enforce minimum relevance
threshold before passing candidates to Cohere. Currently all top-10 RRF results pass to
reranker regardless of score — low-quality candidates consume rerank quota without
improving precision.

**[Planned Next] Pydantic response validation** — validate generate() output structure before
returning to pipeline. Enforce citation presence, answer length bounds, and guardrail
action handling. Prevents silent failures from upstream Bedrock changes.

**[Planned Next] Control ID preservation in sparse preprocessing** — `_sparse_query()` strips stop
words and limits to 5 terms; control identifiers (AC-2, IR-4) appearing after position 5
are dropped. Regex pre-extraction of control IDs before term limiting would ensure they
are always preserved as high-value BM25 anchors. See docs/decision_log.md DL-019.
