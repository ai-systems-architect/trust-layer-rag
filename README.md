# governed-compliance-engine

Governed RAG system for NIST, FISMA, and FedRAMP compliance — hybrid retrieval,
hallucination controls, and full pipeline observability.

**Portfolio:** P2 of 4 — follows [responsible-mlops-risk-engine](https://github.com/ai-systems-architect/responsible-mlops-risk-engine)

---

## Architecture

| Layer | Component | Tool |
|---|---|---|
| Ingestion | PDF + Word parsing, chunking | LibreOffice headless (.docx → PDF conversion) + PyMuPDF |
| Embedding | Dense vectors (1536 dims) | OpenAI text-embedding-3-large — 1536 dims via Matryoshka truncation from 3072, retains ~99% retrieval quality, resolves pgvector HNSW 2000-dim ceiling (DL-018) |
| Vector Store | pgvector + HNSW index | RDS PostgreSQL |
| Query Classification | Rule-based metadata filter inference | Regex classifier in pipeline.py |
| Retrieval | Dense + sparse fused via RRF, metadata pre-filtered | pgvector + tsvector |
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
| Post-RRF quality gate | RRF ranks weak candidates against each other — gate stops noise reaching Cohere |
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

See [docs/evaluation_methodology.md](docs/evaluation_methodology.md) for full metric definitions, formulas, and signal selection rationale.

---

## Known Limitations and Failure Analysis

| # | Failure type | Affected queries | Root cause | Status |
|---|---|---|---|---|
| 1 | BM25 sparse=0 on governance queries | AI RMF, AI 600-1 | Governance language (govern, measure, trustworthy) does not survive stop word stripping as distinctive BM25 tokens | By design — dense-only fallback is correct for abstract language |
| 2 | Control ID truncation by 5-term BM25 limit | Any query with control ID after position 5 | `_sparse_query()` strips stop words and limits to 5 terms — AC-2 or IR-4 appearing late in query dropped | Fixed in DL-019 — regex pre-extraction implemented |
| 3 | Answer relevancy below 0.70 target | All queries | System prompt compliance hedging penalized by RAGAs which rewards concise direct answers | Accepted — fixing requires weakening safety behavior |
| 4 | RAGAs multi-part question fragmentation | Architect-level multi-part questions | RAGAs synthetic question generation partially overlaps original questions | Evaluation set limitation — documented in DL-020 |
| 5 | First hybrid evaluation run invalid | All 20 evaluation queries | BM25 sparse=0 bug present during initial run — hybrid functionally identical to semantic | Resolved before final scores locked |

Failures 1 and 3 are accepted tradeoffs. Failure 2 is resolved. Failures 4 and 5 are evaluation methodology artifacts that do not affect production system quality.

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

```
query → [Input Guardrail] → [Enrich] → [Classify] → Retrieval (pre-filtered) → Reranking → Generation → [Output Guardrail] → response
```

Dual guardrail architecture — input gate blocks before retrieval fires, output gate
prevents overclaiming after generation. A blocked input query costs one Bedrock
apply_guardrail call (~50ms). A blocked output query costs the full pipeline.

**Input Guardrail** — Bedrock Guardrails `apply_guardrail` API checks the raw query
before any retrieval runs. Blocks prompt injection, off-topic queries, and jailbreak
patterns with no downstream token cost.

**Query Enrichment** — Resolves pronouns and ambiguous references in follow-up queries
using recent conversation context before the embedding call. "How does that relate to
least privilege?" becomes "How does AC-6 relate to least privilege in NIST 800-53?"
— the retriever embeds a fully specified query. Claude via Bedrock at `temperature=0.0`
rewrites the query deterministically. Bypassed on first turn, long queries (8+ words),
and queries with no ambiguous pronouns — adds ~150ms only on triggered queries.
Rewrite visible in app UI and Langfuse trace. See docs/decision_log.md DL-025.

**Classify** — Rule-based query classifier infers metadata pre-filters from the
enriched query text. Queries containing NIST 800-53 control IDs (e.g. AC-2, IR-4)
resolve to a `control_family` filter; queries mentioning FedRAMP Moderate resolve to
an `impact_level` filter. Runs on the enriched query so resolved control IDs trigger
the filter even when the original query used a pronoun. See docs/decision_log.md DL-023.

**Ingestion** — NIST 800-53, AI RMF, AI 600-1, and FedRAMP Moderate documents
parsed, chunked, embedded, and stored in pgvector on RDS. Each chunk carries
`control_family` (NIST 800-53 family prefix, extracted from text) and `impact_level`
(FedRAMP impact, source-derived) metadata columns for pre-filter support.

**Retrieval** — Hybrid dense (pgvector HNSW) + sparse (BM25 tsvector) search fused
via Reciprocal Rank Fusion. Returns up to top-10 chunks.

**Post-RRF Quality Gate** — Candidates below `MIN_RRF_SCORE = 0.0150` are dropped
before Cohere sees them. RRF produces a ranked list regardless of absolute match
quality — the gate stops weak candidates from consuming rerank quota. Safety floor
of 3 candidates guaranteed. Threshold derived from empirical score distribution
across 7 representative query types: 6–10 candidates pass per query, average 8.1
of 10; safety floor triggered on 0 of 7 queries. Threshold 0.0150 was set from
first principles — the commonly cited 0.008 does not apply when k=60, because the
theoretical minimum RRF score with top_k=10 is 1/(60+10) = 0.0143, making anything
below that a no-op. See docs/decision_log.md DL-024.

**Reranking** — Cohere rerank-english-v3.0 cross-encoder scores the filtered
candidate set jointly against the query. Returns top-5.

**Generation** — Claude Sonnet 4.5 via Amazon Bedrock.

**Output Guardrail** — Bedrock Guardrails `guardrailConfig` on the converse call.
Catches overclaiming, compliance status assertions, and misconduct in generated answers.

**Evaluation** — RAGAs evaluation against a 20-question golden dataset covering all
four corpus sources including cross-corpus synthesis questions.

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

**[Implemented] Conversational memory (retrieval-side)** — follow-up queries are
rewritten using recent conversation context before the embedding call. Pronouns and
vague references ("that", "it", "this approach") are resolved to their specific
referents so the retriever embeds a fully specified query. Claude at `temperature=0.0`
handles the rewrite deterministically; bypassed on first turn and self-contained
queries. See docs/decision_log.md DL-025.

Long-term memory across sessions — persisting user system profile (impact level,
deployment model, control families reviewed) in RDS keyed by user ID — is not
implemented. Would enable the system to answer "given your Moderate-impact SaaS
system, here are the AC controls you still need to address" rather than answering
generically on every session. Pairs with system profile intake future work item.

**[Production Required] PII filtering** — production deployment requires PII detection and redaction at
query input (before embedding), corpus ingestion (before chunking), and generated
output (before UI rendering). Microsoft Presidio or AWS Comprehend recommended.
Langfuse traces should be scrubbed at source to prevent PII persistence in the
observability store. See docs/decision_log.md DL-017.

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
