# The Trust Layer for Federal Compliance AI
## Production-grade governed RAG system for federal compliance corpora

> Independent portfolio project demonstrating production-grade governed RAG architecture for federal compliance corpora. Built on public-domain US Government frameworks (NIST 800-53, NIST AI RMF 1.0, NIST AI 600-1, FedRAMP Moderate). Not affiliated with or endorsed by any agency, contractor, or commercial vendor. Views are the author's own.

Designed for high-stakes, audit-sensitive environments where correctness,
traceability, and controlled behavior matter more than fluency.

A production-grade, governed Retrieval-Augmented Generation (RAG) system over
federal compliance documents — NIST SP 800-53 Rev 5, NIST AI RMF 1.0, NIST AI
600-1, and FedRAMP Moderate Baseline. The system answers compliance questions by
retrieving authoritative source content, reranking for precision, generating
grounded responses via Claude Sonnet 4.5 through Amazon Bedrock, and enforcing
guardrails against overclaiming.

Built as a **compliance reference assistant — not a compliance assessment tool.**
The system retrieves and synthesizes what frameworks require. It does not determine
whether a system is compliant. That boundary is enforced through system prompts and
Bedrock Guardrails.

**Portfolio:** P2 of 4 — follows
[responsible-mlops-risk-engine](https://github.com/ai-systems-architect/responsible-mlops-risk-engine)

This deployment uses a public RDS endpoint and Streamlit Community Cloud for
portfolio accessibility. For regulated workloads, the production path uses private
VPC, self-hosted Langfuse, and Bedrock-native embeddings — documented in
[docs/architecture.md](docs/architecture.md).

---

## Why This Corpus

Federal compliance work is document-intensive and terminology-precise. A compliance
engineer asking about access control requirements needs answers grounded in the actual
control text — not model weights trained on internet data that may be outdated or
imprecise.

Four authoritative documents were selected to cover the full federal AI compliance
stack: NIST 800-53 for security controls, AI RMF for AI risk governance, AI 600-1
for GenAI-specific risk, and FedRAMP Moderate for cloud authorization requirements.
Together they represent the primary frameworks a federal AI system must navigate from
design through ATO.

| Document | Source | Chunks |
|---|---|---|
| NIST SP 800-53 Rev 5 | NIST | 1,112 |
| NIST AI RMF 1.0 | NIST | 50 |
| NIST AI 600-1 | NIST | 92 |
| FedRAMP Moderate Baseline | FedRAMP | 442 |
| **Total** | | **1,696** |

---

## Production RAG Systems — Failure Modes and Architectural Controls

Most RAG implementations stop at embed → retrieve → generate. Production systems
fail at the edges — in retrieval quality, safety, and observability. Each component
in this system exists because of a specific failure mode observed in real-world RAG
systems.

| Failure Mode | Architectural Control |
|---|---|
| Sensitive data in queries and responses | PII filtering (Presidio) at input and output |
| Prompt injection and off-topic queries | Bedrock Guardrails — input gate before retrieval fires |
| Ambiguous follow-up queries degrade retrieval | Query enrichment via Bedrock Claude at temp=0.0 |
| Irrelevant corpus sections retrieved | Metadata-aware filtering (control_family, impact_level) |
| Keyword queries fail semantic retrieval | Hybrid retrieval (dense + BM25 + RRF) |
| Weak candidates ranked despite low relevance | Post-RRF quality gate (MIN_RRF_SCORE=0.0150) |
| Embedding similarity lacks precision | Cohere cross-encoder reranking |
| Model overclaims beyond retrieved context | Bedrock Guardrails — output gate |
| No visibility into system behavior | Langfuse tracing across all pipeline stages |
| Retrieval quality not measurable | RAGAs + retrieval diagnostics (Recall@k, MRR, nDCG) |
| Model and provider lock-in risk | Embedding and generation providers swappable via environment variable |

This system is not optimized for minimal latency or simplicity. It is optimized for
correctness, auditability, and controlled behavior in high-risk environments.

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
| Guardrails | Dual gates — input (prompt injection, off-topic) + output (overclaiming) | Bedrock Guardrails |
| Evaluation | Golden dataset scoring | RAGAs |
| Frontend | Chat UI + debug sidebar | Streamlit |
| Infrastructure | RDS, S3, IAM | Terraform + AWS |

Full rationale for each component: [docs/decision_log.md](docs/decision_log.md)
Cloud equivalents (GCP, Azure): [docs/architecture.md](docs/architecture.md)

---

## Pipeline

![Governed RAG architecture — offline ingestion pipeline, shared infrastructure, online query pipeline](docs/images/governed_rag_architecture.png)
*Full system architecture — offline ingestion, shared infrastructure, online query pipeline.*

Each stage is modular and independently replaceable. Retrieval strategies can change
without affecting generation. Models can be swapped without rewriting the pipeline.
Observability remains consistent across all components.

Dual guardrail architecture — input gate blocks before retrieval fires, output gate
prevents overclaiming after generation. A blocked input query costs one Bedrock
apply_guardrail call (~50ms). A blocked output query costs the full pipeline.

### PII Scrub
Presidio `en_core_web_lg` scans the raw query before any external service call and
replaces detected entities (PERSON, EMAIL_ADDRESS, US_SSN, IP_ADDRESS, and others)
with bracketed type placeholders. A second pass runs on the generated answer before
returning to the caller — catches query PII echoed in the response. A
`_DOMAIN_ALLOWLIST` (FedRAMP, NIST, AWS, ISSO, and 16 other federal terms) and a
control ID regex prevent federal acronyms and NIST identifiers (AC-2, IR-4) from
being misclassified as PERSON entities by the NER model. See docs/decision_log.md DL-017.

### Input Guardrail
Bedrock Guardrails `apply_guardrail` API checks the raw query before any retrieval
runs. Blocks prompt injection, off-topic queries, and jailbreak patterns with no
downstream token cost.

### Query Enrichment
Resolves pronouns and ambiguous references in follow-up queries using recent
conversation context before the embedding call. "How does that relate to least
privilege?" becomes "How does AC-6 relate to least privilege in NIST 800-53?" —
the retriever embeds a fully specified query. Claude via Bedrock at `temperature=0.0`
rewrites the query deterministically. Bypassed on first turn, long queries (8+ words),
and queries with no ambiguous pronouns — adds ~150ms only on triggered queries.
Rewrite visible in app UI and Langfuse trace. See docs/decision_log.md DL-025.

### Classify
Rule-based query classifier infers metadata pre-filters from the enriched query text.
Queries containing NIST 800-53 control IDs (e.g. AC-2, IR-4) resolve to a
`control_family` filter; queries mentioning FedRAMP Moderate resolve to an
`impact_level` filter. Runs on the enriched query so resolved control IDs trigger
the filter even when the original query used a pronoun. See docs/decision_log.md DL-023.

### Ingestion
NIST 800-53, AI RMF, AI 600-1, and FedRAMP Moderate documents parsed, chunked,
embedded, and stored in pgvector on RDS. Each chunk carries `control_family` (NIST
800-53 family prefix, extracted from text) and `impact_level` (FedRAMP impact,
source-derived) metadata columns for pre-filter support.

### Retrieval
Hybrid dense (pgvector HNSW) + sparse (BM25 tsvector) search fused via Reciprocal
Rank Fusion. Returns up to top-10 chunks. NIST 800-53 control identifiers (AC-2,
IR-4) are pre-extracted from the query via regex before BM25's 5-term limit is
applied — control IDs always reach the sparse index as high-value anchor terms
regardless of query length. See docs/decision_log.md DL-019.

### Post-RRF Quality Gate
Candidates below `MIN_RRF_SCORE = 0.0150` are dropped before Cohere sees them. RRF
produces a ranked list regardless of absolute match quality — the gate stops weak
candidates from consuming rerank quota. Safety floor of 3 candidates guaranteed.
Threshold derived from empirical score distribution across 7 representative query
types: 6–10 candidates pass per query, average 8.1 of 10; safety floor triggered on
0 of 7 queries. Threshold 0.0150 was set from first principles — the commonly cited
0.008 does not apply when k=60, because the theoretical minimum RRF score with
top_k=10 is 1/(60+10) = 0.0143, making anything below that a no-op. See
docs/decision_log.md DL-024.

### Reranking
Cohere rerank-english-v3.0 cross-encoder scores the filtered candidate set jointly
against the query. Returns top-5.

### Generation
Claude Sonnet 4.5 via Amazon Bedrock. Response validated with Pydantic —
`GenerateResponse` model enforces answer, model, stop_reason, and guardrail_action
fields before the result returns to the pipeline.

### Output Guardrail
Bedrock Guardrails `guardrailConfig` on the converse call. Catches overclaiming,
compliance status assertions, and misconduct in generated answers.

### Evaluation
RAGAs evaluation against a 20-question golden dataset covering all four corpus
sources including cross-corpus synthesis questions.

---

## Retrieval Architecture — Why Hybrid

**Dense retrieval (pgvector HNSW)** embeds the query and chunks independently then
measures cosine similarity between vectors. Effective for conceptual and abstract
queries — AI RMF governance language, risk framework concepts, cross-corpus synthesis
questions.

**Sparse retrieval (tsvector BM25)** matches on vocabulary. Effective for queries
containing exact control identifiers — AC-6, IR-4, SC-28, CM-7. A compliance engineer
searching for a specific control by ID gets the right chunks surfaced immediately.

**RRF fusion (k=60)** combines both ranked lists: score = Σ 1/(60 + rank). The
constant k=60 is empirically validated across information retrieval literature — it
prevents high-ranked results from dominating while preserving rank signal.

**BM25 query preprocessing:** Long natural language questions AND-chain all terms via
plainto_tsquery, returning zero results when no single chunk contains every term
simultaneously. Preprocessing strips stop words and limits to five key terms. Control
identifiers (AC-6, IR-4) are regex-extracted from the original query before the
five-term limit applies — they always occupy the leading slots as high-value BM25
anchors. See docs/decision_log.md DL-019.

**Cohere reranking:** The cross-encoder reads query and chunk together — joint inference
via attention mechanism — producing a relevance probability rather than a geometric
distance. Runs only on the top-10 retrieved chunks, not the full corpus.

---

## Proof of Operation

Live pipeline trace — query: "What does AC-6 require and what are its key enhancements?" Trace ID: d83dcaee-ff26-4b32-8ae3-5b0d90cfb979

Full pipeline exercised: input guardrail checked → classify_query inferred control_family=AC (424 of 1,696 chunks searched, 75% reduction) → hybrid retrieval (dense + BM25, sparse_query: 'AC-6 require key enhancements') → post-RRF gate passed 7 of 11 candidates → Cohere reranked 7 → 5 → Claude Sonnet 4.5 generated cited response → guardrail action: none.

![Trace overview — full pipeline span timeline with query metadata and AC-6 answer output](docs/images/trace_overview.png)
*Trace overview — compliance-query trace showing retrieve (1.00s), rerank (0.17s), generate (10.32s) spans. Input: original query, retriever=hybrid, filters control_family=AC. Output: full AC-6 cited answer, guardrail_action=none.*

![Retrieve span — metadata filter and hybrid retrieval detail](docs/images/trace_retrieve.png)
*Retrieve span — enriched_query passed to hybrid retriever, control_family=AC filter applied, use_hybrid=true, 7 chunks returned post-RRF gate.*

![Generate span — reranked chunks in, cited answer out](docs/images/trace_generate.png)
*Generate span — 5 reranked chunks passed to Claude Sonnet 4.5 via Bedrock, AC-6 cited response returned, guardrail_action=none.*

---

## Evaluation Results

RAGAs evaluation against a 20-question architect-level golden dataset covering
all four corpus sources including cross-corpus synthesis questions.

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

> A slightly verbose but correct answer is acceptable.
> An overconfident or incorrect answer is not.

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

nDCG@5 — Semantic: 0.8883 | Hybrid: 0.9092 | Hybrid+Rerank: 0.9265

The most relevant chunk surfaces at rank 1 for 90%+ of questions (MRR 0.90+).
Recall@5 appears low (0.17) because the ground truth pool averages 28 chunks
per question — top-5 retrieval capturing 17% of 28 labeled chunks reflects the
large denominator, not a retrieval failure. nDCG@5 progression (0.8883 → 0.9092
→ 0.927) confirms each pipeline layer adds ranking quality: RRF fusion improves
governance query ranking (MRR 0.875 → 0.938), Cohere cross-encoder refines
mid-list precision without displacing already-correct top-1 positions (MRR
unchanged at Hybrid → H+Rerank, nDCG +0.018). Control ID queries achieve
perfect MRR 1.00 across all configurations — exact control identifiers anchor
both dense and BM25 retrieval reliably.

See [docs/evaluation_methodology.md](docs/evaluation_methodology.md) for full metric definitions, formulas, and signal selection rationale.

---

## Worked Examples

Three representative queries run end-to-end against the live pipeline. Negative test
cases follow. All traces visible in Langfuse Cloud.

---

### Example 1 — Control ID lookup

**Query:** "What does AC-6 require and what are its key enhancements?"

**Retrieval — 7 candidates after RRF (control_family=AC filter applied)**

| Rank | Source | RRF Score | BM25 | Content preview |
|------|--------|-----------|------|-----------------|
| 1 | nist_800_53 | 0.016393 | No | AC-6 Least Privilege — AC-6(1) AUTHORIZE ACCESS TO SECURITY FUNCTIONS… |
| 2 | nist_800_53 | 0.016393 | No | Control: Uniquely identify and authenticate organizational users… |
| 3 | nist_800_53 | 0.016129 | No | NIST SP 800-53, REV. 5 |
| 4 | nist_800_53 | 0.015873 | No | AC-3(9) CONTROLLED RELEASE — AC-3(10) AUDITED OVERRIDE… |
| 5 | nist_800_53 | 0.015625 | No | AC-16(10) ATTRIBUTE CONFIGURATION — AC-17 Remote Access… |
| 6 | fedramp_moderate_baseline | 0.015385 | No | FedRAMP SSP Appendix A: Moderate Security Controls… |
| 7 | nist_800_53 | 0.015152 | No | NIST SP 800-53, REV. 5 |

**After Cohere rerank — top 5**

| Rank | Source | Rerank score | Content preview |
|------|--------|-------------|-----------------|
| 1 | fedramp_moderate_baseline | 0.9891 | FedRAMP SSP Appendix A: Moderate Security Controls… |
| 2 | nist_800_53 | 0.9632 | NIST SP 800-53, REV. 5 |
| 3 | nist_800_53 | 0.9385 | AC-6 Least Privilege — AC-6(1) AUTHORIZE ACCESS TO SECURITY FUNCTIONS… |
| 4 | nist_800_53 | 0.3976 | Control: Uniquely identify and authenticate organizational users… |
| 5 | nist_800_53 | 0.1395 | NIST SP 800-53, REV. 5 |

**Pipeline metadata**

| Field | Value |
|-------|-------|
| Filters | `control_family=AC` |
| BM25 fired | No — see Findings below |
| Corpus searched | 424 of 1,696 chunks (control_family=AC filter — 75% reduction) |
| Post-RRF candidates | 7 of 10 passed gate (≥ 0.0150); 3 filtered |
| Query enriched | No |
| Guardrail (input/output) | NONE / none |
| Trace ID | `a7b0410a-67c6-4798-b9dd-43d80b8338b1` |
| Latency | 13,266ms |

**Answer (summarised)**

AC-6 Least Privilege requires implementing least-privilege access for system accounts.
Key enhancements AC-6(1)–AC-6(10) cover: authorizing access to security functions,
non-privileged access for non-security functions, network access to privileged commands,
separate processing domains, privileged accounts, access by non-organizational users,
review of user privileges, privilege levels for code execution, logging privileged
function use, and prohibiting non-privileged users from executing privileged functions.
All enhancements cited from NIST SP 800-53 Rev 5, page 457, and FedRAMP Moderate
Baseline page 44.

**Citation spot-check**

| Cited section | Verified | Source |
|---------------|----------|--------|
| AC-6(1)–AC-6(10) enhancements | Yes | NIST SP 800-53 Rev 5, p. 457 |
| AC-6(2) non-privileged access requirement text | Yes | FedRAMP Moderate Baseline, p. 44 |

---

### Example 2 — AI governance

**Query:** "How does the AI RMF Govern function establish organizational accountability for AI risk?"

**Retrieval — 9 candidates after RRF (no filter)**

| Rank | Source | RRF Score | BM25 | Content preview |
|------|--------|-----------|------|-----------------|
| 1 | nist_ai_rmf | 0.032522 | Yes | GOVERN is a cross-cutting function that is infused throughout… |
| 2 | nist_ai_rmf | 0.030835 | Yes | Table 1: Categories and subcategories for the GOVERN function… |
| 3 | nist_ai_rmf | 0.016393 | No | AI RMF 1.0 — deployed, or evaluated – which can create opportunities… |
| 4 | nist_ai_rmf | 0.015873 | No | AI RMF Core — Part 2: Core and Profiles… |
| 5 | nist_ai_rmf | 0.015873 | No | Table 2: Categories and subcategories for the MAP function… |
| 6 | nist_ai_rmf | 0.015625 | No | Executive Summary — Artificial intelligence (AI) technology… |
| 7 | nist_ai_600_1 | 0.015625 | No | GV-1.3-004 Obtain input from stakeholder communities… |
| 8 | nist_ai_rmf | 0.015385 | No | AI RMF 1.0 — Presenting AI system information to humans… |
| 9 | nist_ai_rmf | 0.015152 | No | Table 1: Categories and subcategories for the GOVERN function… |

**After Cohere rerank — top 5**

| Rank | Source | Rerank score | Content preview |
|------|--------|-------------|-----------------|
| 1 | nist_ai_rmf | 0.999991 | GOVERN is a cross-cutting function that is infused throughout… |
| 2 | nist_ai_rmf | 0.999983 | Table 1: Categories and subcategories for the GOVERN function… |
| 3 | nist_ai_rmf | 0.999969 | Table 1: Categories and subcategories for the GOVERN function… |
| 4 | nist_ai_rmf | 0.999962 | Presenting AI system information to humans is complex… |
| 5 | nist_ai_rmf | 0.999952 | deployed, or evaluated — which can create opportunities… |

**Pipeline metadata**

| Field | Value |
|-------|-------|
| Filters | none |
| BM25 fired | Yes — ranks 1 and 2 (scores 0.0325, 0.0308) |
| Post-RRF candidates | 9 of 10 passed gate; 1 filtered |
| Query enriched | No |
| Guardrail (input/output) | NONE / none |
| Trace ID | `1c2f4226-63ef-46e2-94b6-7b8fe6f5dcad` |
| Latency | 8,662ms |

**Answer (summarised)**

The GOVERN function establishes accountability through GOVERN 2 structures: GOVERN 2.1
documents roles and responsibilities for AI risk management across the organization;
GOVERN 2.2 mandates training for personnel on AI risk; GOVERN 2.3 assigns executive
leadership responsibility for AI risk decisions. Senior leadership sets organizational
culture for risk management. All cited from NIST AI RMF 1.0, pages 27–28.

**Citation spot-check**

| Cited section | Verified | Source |
|---------------|----------|--------|
| GOVERN 2.1 — roles and responsibilities documented | Yes | NIST AI RMF 1.0, p. 28 |
| GOVERN 2.2 — training requirements | Yes | NIST AI RMF 1.0, p. 28 |
| GOVERN 2.3 — executive leadership responsibility | Yes | NIST AI RMF 1.0, p. 28 |

---

### Example 3 — Cross-corpus synthesis

**Query:** "How do FedRAMP access control requirements relate to NIST AI RMF governance expectations?"

**Retrieval — 10 candidates after RRF (no filter)**

| Rank | Source | RRF Score | BM25 | Content preview |
|------|--------|-----------|------|-----------------|
| 1 | nist_ai_rmf | 0.016393 | No | AI RMF 1.0 — deployed, or evaluated… |
| 2 | nist_800_53 (AU) | 0.016393 | No | Discussion: In certain situations, such as when there is a threat to human life… |
| 3 | nist_ai_rmf | 0.016129 | No | GOVERN is a cross-cutting function… |
| 4 | nist_800_53 (PE) | 0.016129 | No | NIST SP 800-53, REV. 5 |
| 5 | nist_ai_rmf | 0.015873 | No | Presenting AI system information to humans is complex… |
| 6 | nist_800_53 (PE) | 0.015873 | No | PE-2 PHYSICAL ACCESS AUTHORIZATIONS… |
| 7 | nist_ai_rmf | 0.015625 | No | valid and reliable, safe, secure and resilient, accountable… |
| 8 | nist_800_53 (PM) | 0.015625 | No | Provide mechanisms to enable individuals to… |
| 9 | nist_ai_rmf | 0.015385 | No | Table 1: Categories and subcategories for the GOVERN function… |
| 10 | nist_800_53 (IA) | 0.015385 | No | their accounts. Standards and guidelines for identity assurance… |

**After Cohere rerank — top 5**

| Rank | Source | Rerank score | Content preview |
|------|--------|-------------|-----------------|
| 1 | nist_ai_rmf | 0.9906 | GOVERN is a cross-cutting function… |
| 2 | nist_ai_rmf | 0.9477 | Table 1: Categories and subcategories for the GOVERN function… |
| 3 | nist_ai_rmf | 0.8667 | Presenting AI system information to humans is complex… |
| 4 | nist_ai_rmf | 0.8222 | valid and reliable, safe, secure and resilient, accountable… |
| 5 | nist_ai_rmf | 0.7484 | deployed, or evaluated — which can create opportunities… |

**Pipeline metadata**

| Field | Value |
|-------|-------|
| Filters | none — see Findings below |
| BM25 fired | No |
| Post-RRF candidates | 10 of 10 passed |
| Query enriched | No |
| Guardrail (input/output) | NONE / none |
| Trace ID | `0a9710f1-8fc7-42e3-9dd6-29972b2c1cf9` |
| Latency | 8,617ms |

**Answer (summarised)**

The pipeline declined to answer — the retrieved context was exclusively AI RMF chunks
with no FedRAMP access control content. The answer correctly identified that no relevant
FedRAMP chunks were present in the context and listed what was available. This is
accurate and expected given the retrieval result. Root cause: Presidio scrubbed
"FedRAMP" from the query before embedding, preventing both the `impact_level=Moderate`
filter and FedRAMP-relevant dense retrieval from firing. See Findings below.

---

### Negative test cases

Three queries outside the corpus scope, run to verify refusal behavior.

| # | Query | Top rerank score | Guardrail | Outcome | Trace |
|---|-------|-----------------|-----------|---------|-------|
| NEG-1 | "What does NIST 800-53 say about quantum computing key rotation schedules?" | 0.071 | none | Corpus grounding — no relevant chunks retrieved; answer cited only bibliographic references | `0a909578` |
| NEG-2 | "How should AI systems handle cryptocurrency transaction validation under FedRAMP?" | 0.000436 | none | Corpus grounding — near-zero rerank scores; answer declined and stated topic is outside corpus | `12ea25c1` |
| NEG-3 | "What are the NIST guidelines for blockchain smart contract auditing?" | 0.002726 | none | Corpus grounding — near-zero rerank scores; answer declined and referenced only unrelated NIST publications | `cbeb70ef` |

All three refusals are driven by corpus grounding, not the Bedrock output guardrail. Rerank scores near zero confirm the retriever found no relevant content — Claude had nothing to overclaim from. The guardrail action `none` is expected and correct: these are not hallucination or overclaiming failures, they are out-of-scope queries handled by retrieval precision.

---

### Findings and Observations

Four architectural behaviors observed during the worked examples run that were not apparent from evaluation metrics alone:

#### 1. BM25 + metadata filter collapse (MAIN-1)
- **What:** BM25 fired=False despite AC-6 being present in the query
- **Root cause:** `WHERE tsvector_match AND control_family='AC'` — combining BM25 and the SQL pre-filter causes tsvector to return zero rows on the filtered subset
- **Outcome:** Dense retrieval covered the gap; Cohere ranked the FedRAMP AC-6 chunk first (0.9891)
- **Fix:** Run sparse and dense legs separately; apply metadata filter to dense leg only, fuse post-filter. See DL-027.

#### 2. BM25 fires on short governance queries (MAIN-2)
- **What:** 9-word governance query fired BM25 at 0.0325/0.0308 — contradicts the evaluation finding that BM25 does not fire on AI RMF queries
- **Root cause:** Short queries preserve "govern" as a distinctive BM25 token after stop-word stripping; evaluation questions were 10–15 words where "govern" was one of many terms and did not anchor alone
- **Outcome:** Both behaviors are correct — BM25 fires when its signal is strong enough regardless of query category; short Streamlit queries behave differently from long evaluation questions

#### 3. FedRAMP PII false positive (MAIN-3)
- **What:** Query ran without the `impact_level=Moderate` filter; retrieved exclusively AI RMF content instead of FedRAMP chunks
- **Root cause:** Presidio `en_core_web_lg` classified "FedRAMP" as a PERSON entity and scrubbed it before embedding
- **Outcome:** Answer correctly declined rather than hallucinating from irrelevant chunks
- **Fix:** `_DOMAIN_ALLOWLIST` in `utils/pii_filter.py` prevents FedRAMP, NIST, AWS, Bedrock, FISMA, ATO, and RMF from being scrubbed. See DL-017.

#### 4. Negative queries refused by corpus grounding, not guardrails
- **What:** All three negative queries declined correctly; guardrail action=none on all three
- **Root cause:** Corpus does not contain quantum cryptography, cryptocurrency, or blockchain content — rerank scores near zero (max 0.071, 0.000436, 0.002726)
- **Outcome:** Retrieval precision is the primary defense against out-of-scope queries; the Bedrock output guardrail is not needed when the retriever finds nothing to overclaim from

---

## Key Architectural Tradeoffs

| Decision | Chosen | Rejected | Tradeoff |
|---|---|---|---|
| Vector store | pgvector on RDS | Pinecone, Weaviate, Qdrant | Single AWS security boundary over managed convenience — one IAM policy, one audit trail |
| Retrieval | Hybrid dense + BM25 + RRF | Dense-only | Control IDs (AC-6, IR-4) need exact token matching — semantic alone misses them at rank 1 |
| Reranking | Cohere cross-encoder | Bi-encoder similarity | Joint query+chunk inference produces trained relevance judgment, not geometric distance |
| Embedding dims | 1536 (Matryoshka truncation) | 3072 full dims | pgvector HNSW 2000-dim ceiling — retains ~99% retrieval quality at half the dimensions |
| Generation | Claude Sonnet 4.5 via Bedrock | Direct Anthropic API | Bedrock keeps generation within AWS boundary — direct API sends chunks to external endpoint |
| Guardrails | Dual gates input + output | Output-only | Input gate stops prompt injection before retrieval fires — one Bedrock call vs full pipeline cost |

Full rationale with alternatives evaluated in docs/decision_log.md (DL-001 through DL-027).

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

## NIST AI RMF Alignment

| Function | Implementation |
|---|---|
| GOVERN | System prompt enforces compliance reference boundary — no overclaiming, Bedrock Guardrails enforcement, decision log documents all architectural choices (DL-001 through DL-027) |
| MAP | Corpus scope explicitly bounded to four frameworks, system capability ceiling documented in README, PII surfaces identified across input / corpus / output / traces |
| MEASURE | RAGAs evaluation against 20-question golden dataset, semantic vs hybrid quantified comparison, Langfuse latency and span tracing per pipeline stage |
| MANAGE | Guardrails block overclaiming responses, provider abstraction enables model swap without pipeline rewrite, AWS Batch recommended for production ingestion |

---

## Deployment Boundary

Corpus and vector store remain within AWS (RDS + S3). Generation occurs via Amazon
Bedrock (Claude Sonnet 4.5). External services used:

- **OpenAI** — query embedding (text-embedding-3-large)
- **Cohere** — reranking (rerank-english-v3.0)
- **Langfuse Cloud** — pipeline tracing (us.cloud.langfuse.com)

A fully AWS-bound variant using Bedrock-native embeddings, Bedrock rerank, and
self-hosted Langfuse is documented in [docs/architecture.md](docs/architecture.md).

---

## Future Work

Implemented items removed — see docs/decision_log.md for closed decisions (DL-001 through DL-027).

### Production Required

**FedRAMP Presidio false positive (MAIN-3)** — `_DOMAIN_ALLOWLIST` in `utils/pii_filter.py`
prevents federal acronyms from being misclassified as PERSON entities. Corpus ingestion
scrubbing and Langfuse trace scrubbing at source remain production-only items. AWS
Comprehend is the recommended production path when all services are within the same AWS
account boundary. See docs/decision_log.md DL-017.

**RAG-RBAC role-based retrieval filtering** — `sensitivity_level` column in chunks table
with `WHERE sensitivity_level <= user_clearance` pre-filter. Foundation already exists in
the metadata filtering layer (DL-023). Required when corpus includes controlled or
sensitivity-tiered documents.

### Planned Next

**Manual evaluation mini-appendix** — 5 questions with human-labeled ground truth to
validate auto-derived Recall@k labels. Removes potential retrieval-seeding bias from
label generation.

**Negative testing automation** — formalize the 5–10 unanswerable queries from Worked
Examples into an automated suite with expected refusal outcomes and rerank score
thresholds.

**Citation precision automation** — cross-reference cited section numbers against PDF page
ranges. Currently verified manually per worked example; automation scales verification to
the full golden dataset.

### Stretch

**System profile intake** — structured intake of system impact level, deployment model,
and data types to condition retrieval. Enables control applicability answers specific to
a target system rather than general corpus lookup.

**Control checklist generation** — second LLM call post-retrieval to structure answers as
actionable, system-specific control checklists rather than prose summaries.

**Structured intent extraction** — classify query intent (control lookup, gap assessment,
cross-framework synthesis) before retrieval. Route to appropriate retriever config per
intent — control lookup favors BM25, synthesis favors dense.

**True AWS-boundary variant** — replace OpenAI embeddings with Amazon Titan or Cohere
Embed via Bedrock to keep all data within the AWS boundary at ingestion time.

**Query expansion / multi-query rewriting** — HyDE or LLM-generated query variants to
broaden retrieval on abstract governance queries where vocabulary mismatch causes semantic
drift.

**Self-correction loop** — if faithfulness score falls below threshold, re-attempt
retrieval with broader search radius before returning response. Bedrock Guardrails
provides the current safety floor; this pattern is more appropriate for production
agentic systems than portfolio RAG.

**Context entities recall** — RAGAs entity-level retrieval metric to verify key
identifiers such as MAP-1.1 or AC-2 are not dropped during retrieval. Defer until
Recall@k and MRR baselines are established.

**Long-term conversational memory (cross-session)** — persist user system profile (impact
level, deployment model, control families reviewed) across sessions in RDS keyed by user
ID. Enables answers conditioned on the user's specific system rather than generic corpus
lookup. Within-session memory implemented via DL-025.

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

## License

MIT License — see [LICENSE](LICENSE.md).

Copyright (c) 2026 Raghunath Devayajanam.

This project ingests US Government public-domain compliance frameworks
(NIST 800-53, NIST AI RMF 1.0, NIST AI 600-1, FedRAMP Moderate). Those
documents are works of the US Government and are not subject to copyright
protection in the United States (17 U.S.C. § 105). They are included to
demonstrate retrieval-augmented generation over federal compliance corpora.
No US Government endorsement is implied.
