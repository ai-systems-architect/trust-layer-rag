# Architecture — governed-compliance-engine

High-level system design. For why each component was chosen over alternatives,
see docs/decision_log.md.

---

## Overview

Governed RAG system for NIST, FISMA, and FedRAMP compliance. Ingests four
federal regulatory documents (three PDFs via PyMuPDF, FedRAMP Word document
converted to PDF via LibreOffice), stores embeddings in pgvector on RDS,
retrieves via hybrid dense + sparse fusion, re-ranks with Cohere, generates
citation-enforced responses via Claude Sonnet 4.5 on Bedrock, and enforces
hallucination controls via Bedrock Guardrails. Every pipeline call is traced
end-to-end in Langfuse Cloud.

---

## System Architecture

![Governed RAG architecture — three-pipeline view](images/governed_rag_architecture.png)
*System architecture overview — see ASCII pipeline diagrams below for per-stage decision log references.*

---

## Pipeline

### Ingestion (one-time)

```
NIST 800-53 / AI RMF / AI 600-1 (PDF) + FedRAMP Moderate (.docx → PDF)
        │
        ▼
   Document Ingestion
   (PyMuPDF extraction + tiktoken chunking — 600 tokens / 100 overlap)
   [production: AWS Batch job — see DL-016]
        │
        ▼
   Embedding
   (OpenAI text-embedding-3-large — 1536 dims, Matryoshka truncation)
        │
        ▼
   pgvector on RDS
   (HNSW cosine index + GIN tsvector index)
```

### Query pipeline (per request)

```
User Query
        │
        ▼
   PII Scrub — Presidio (query input)
        │
        ▼
   Input Guardrail — Bedrock Guardrails
   (prompt injection, off-topic queries — blocked → early return, no retrieval cost)
        │
        ▼
   Query Enrichment — Bedrock Claude temp=0.0  (DL-025)
   (pronoun resolution: "that" → "AC-6"; bypass on first turn / 8+ words / no pronouns)
        │
        ▼
   Classify Query — rule-based  (DL-023)
   (infer control_family + impact_level metadata pre-filters from query text)
        │
        ▼
   Metadata-Filtered Hybrid Retrieval
   ┌──────────────┬──────────────┐
   Dense           Sparse
   (pgvector HNSW) (tsvector / BM25)
   └──────────────┴──────────────┘
        │  RRF fusion — top-10  (DL-008)
        ▼
   Post-RRF Quality Gate  (DL-024)
   (MIN_RRF_SCORE=0.0150 — drops weak candidates; safety floor: 3 candidates)
        │
        ▼
   Cohere Rerank — cross-encoder, top-10 → top-5  (DL-005)
        │
        ▼
   Claude Sonnet 4.5 via Bedrock — citation-enforced generation  (DL-004)
        │
        ▼
   Output Guardrail — Bedrock Guardrails
   (overclaiming, hallucination controls)
        │
        ▼
   PII Scrub — Presidio (generated output)  (DL-017)
        │
        ▼
   Response ──► Langfuse Trace
                (span-level: retrieve → rerank → generate)
```

---

## Component Stack

| Layer | Component | Purpose |
|---|---|---|
| Ingestion | PyMuPDF + LibreOffice (FedRAMP conversion) | Parse and chunk four federal regulatory documents |
| Embedding | OpenAI text-embedding-3-large | 1536-dim dense vectors (Matryoshka truncation — see DL-018) |
| Vector Store | pgvector on Amazon RDS | HNSW index, cosine similarity, single security boundary |
| Retrieval | pgvector (dense) + tsvector (sparse) + RRF | Hybrid fusion — exact citations + semantic queries |
| Re-ranking | Cohere rerank-english-v3.0 | Cross-encoder precision over top-10 candidates |
| Generation | Claude Sonnet 4.5 via Amazon Bedrock | Citation-enforced regulatory responses |
| Guardrails | Amazon Bedrock Guardrails | Dual gates — input (prompt injection, off-topic queries before retrieval fires) + output (overclaiming, hallucination controls) |
| Tracing | Langfuse Cloud (us.cloud.langfuse.com) | End-to-end pipeline observability |
| Evaluation | RAGAs | Faithfulness + retrieval precision scoring |
| Frontend | Streamlit | Chat UI + debug sidebar |
| Object Storage | Amazon S3 | Raw PDFs (raw/) + processed chunks (processed/) |
| Infrastructure | Terraform + scripts/rds_start.py + scripts/rds_stop.py | Provisioning, RDS lifecycle management |

---

## Security Boundary

**Current portfolio deployment:** RDS has a public endpoint (required for
Streamlit Community Cloud on GCP — see DL-015). SSL enforced via
rds.force_ssl=1. Corpus is public NIST documents — no sensitive data at risk.

**Data that leaves AWS in current deployment:**
- OpenAI text-embedding-3-large — query text sent to OpenAI at embed time
- Cohere rerank-english-v3.0 — top-10 chunks sent to Cohere at rerank time
- Langfuse Cloud (us.cloud.langfuse.com) — pipeline traces including query text

**Data that stays in AWS:**
- pgvector on RDS — all embeddings and corpus chunks
- Amazon Bedrock — generation stays within AWS managed boundary
- S3 — raw PDFs and processed chunks

**Production path:** Move Streamlit inside AWS (ECS Fargate, private subnet),
remove public RDS endpoint, swap OpenAI for Titan embed and Cohere for Bedrock
rerank — full AWS boundary achieved. See Network Architecture section below.

---

## Provider Abstraction

Embedding and generation providers are swappable via environment variable
with no pipeline code changes:

| Variable | Current | Swap options |
|---|---|---|
| `EMBEDDING_PROVIDER` | `openai` | `bedrock`, `cohere` |
| `GENERATION_PROVIDER` | `bedrock` | no change needed for Claude |

Bedrock Guardrails is the only hard AWS dependency by design.

---

## Cloud Equivalents

### GCP Stack

| AWS Component | GCP Equivalent |
|---|---|
| Amazon RDS + pgvector | AlloyDB for PostgreSQL + pgvector |
| pgvector (managed vector DB alternative) | Vertex AI Vector Search — managed, Pinecone-equivalent on GCP |
| Amazon Bedrock (Claude) | Vertex AI + Claude via Vertex Model Garden |
| Amazon Bedrock Guardrails | Vertex AI Model Armor |
| OpenAI Embeddings | Vertex AI text-embedding-004 (or keep OpenAI) |
| Cohere Rerank | Vertex AI Ranking API |
| LangChain orchestration | Google Agent Development Kit (ADK) — GCP-native alternative |
| Amazon S3 | Google Cloud Storage (GCS) — single bucket, same prefix pattern |
| AWS IAM | GCP IAM + Workload Identity |
| Terraform | Terraform (google provider) or Google Cloud Deployment Manager |
| Langfuse Cloud | Langfuse Cloud (cloud-agnostic) or self-hosted on GKE |

### Azure Stack

| AWS Component | Azure Equivalent |
|---|---|
| Amazon RDS + pgvector | Azure Database for PostgreSQL Flexible Server + pgvector |
| pgvector (managed vector DB alternative) | Azure AI Search — managed, Pinecone-equivalent on Azure |
| Amazon Bedrock (Claude) | Azure AI Foundry + Claude via Azure Marketplace |
| Amazon Bedrock Guardrails | Azure AI Content Safety |
| OpenAI Embeddings | Azure OpenAI Service (text-embedding-3-large — identical model) |
| Cohere Rerank | Azure AI Search semantic ranker |
| LangChain orchestration | LangChain (cloud-agnostic) or Semantic Kernel — Microsoft-native orchestration framework |
| Amazon S3 | Azure Blob Storage — single container, same prefix pattern |
| AWS IAM | Azure Managed Identity + RBAC |
| Terraform | Terraform (azurerm provider) or Azure Bicep |
| Langfuse Cloud | Langfuse Cloud (cloud-agnostic) or self-hosted on AKS |

### Managed Vector DB Alternatives (cloud-agnostic)

If compliance boundary is not a constraint, these replace pgvector entirely:

| Option | Best fit |
|---|---|
| Pinecone | Non-regulated workloads, corpus > 1M vectors, simple API |
| Weaviate Cloud | Multi-modal search, strong GraphQL API |
| Qdrant Cloud | High-throughput retrieval, Rust-based performance |

---

## Network Architecture

### Current — Portfolio Deployment

```
User Browser
↓
Streamlit Community Cloud (GCP us-central1) — free tier
↓ SSL/TLS over public internet
RDS PostgreSQL (AWS us-east-1) — public endpoint
↓ private
pgvector index + compliance corpus
```

Streamlit Community Cloud runs on Google Cloud Platform — outside
AWS entirely. RDS requires a public endpoint to accept connections
from Streamlit. Security enforced via SSL (rds.force_ssl=1) and
strong password. Default VPC used — dedicated VPC adds complexity
without security benefit given public endpoint requirement.
Corpus is public NIST documents — no sensitive data.
See docs/decision_log.md DL-015.

### PII Filtering (Production Requirement)

Production deployments require PII filtering at three layers: query input
before embedding, corpus ingestion before chunking, and generated output
before UI rendering. Langfuse traces must be scrubbed at source to prevent
PII persistence in the observability store. See docs/decision_log.md DL-017.

### Production Enhancement — Full AWS Deployment

Moving to production requires relocating the application layer
inside AWS to eliminate the public RDS endpoint:

```
User Browser
↓
AWS Application Load Balancer (public subnet)
↓
ECS Fargate — Streamlit app (private subnet)
↓ VPC internal only
RDS PostgreSQL (private subnet) — no public endpoint
```

**Changes required:**
- Dedicated VPC with public and private subnets across two AZs
- ECS Fargate or EC2 for Streamlit in private subnet
- Application Load Balancer in public subnet
- RDS moves to private subnet — publicly_accessible = false
- Security group: RDS accepts port 5432 from app security group only
- SSM Session Manager for developer access — no bastion EC2 needed
- No NAT Gateway required if Bedrock accessed via VPC endpoint

**Terraform impact:**
Application connection string does not change — only infrastructure
topology changes. Terraform modules are structured to support this
migration. Estimated additional Terraform: ~100 lines.

### Vector Store — Current Choice and Migration Trigger

Vector store: pgvector on RDS — embeddings, metadata, and BM25 sparse
index co-located in a single AWS boundary. One service, one IAM policy,
one audit trail. Right-sized for this corpus (~5K chunks, <100K at scale).

**When to migrate away from pgvector:**
At 10M+ vectors or sub-10ms P99 latency requirements, Qdrant self-hosted
outperforms meaningfully. Trigger: HNSW query latency exceeds 100ms at
peak load, or corpus crosses 1M chunks. Migration path: swap the vector
store adapter only — retrieval interface is abstracted, application code
does not change. See docs/decision_log.md DL-002.

**If corpus expands beyond current four documents:**
Metadata filtering by source or impact level recommended — pgvector WHERE
clause pre-filter before HNSW search reduces candidate set and improves
precision without schema changes.

### Why Not Dedicated VPC Now

Dedicated VPC only provides meaningful security when the application
layer is co-located inside AWS. With Streamlit on GCP, a dedicated
VPC with public RDS has identical security posture to default VPC
with public RDS — same exposure, more Terraform code. The production
enhancement above is the architecturally correct path — documented
here for completeness and interview discussion.

---

## Pipeline Stages

Retrieval, reranking, and generation are deliberately separate stages.
Step 4 outputs ranked chunks only — no LLM called yet. This boundary
matters: if the right chunks are not in the top-10, nothing downstream
recovers it. Validate retrieval in isolation before proceeding to reranking.

```
Retrieval (Step 4) → Reranking (Step 5) → Generation (Step 7)
```

Both retrievers (semantic and hybrid) return identical chunk shape so
reranking and RAGAs evaluation (Step 8) can swap between semantic-only
and hybrid without downstream changes.

**Retriever behavior by corpus:**
BM25 sparse retrieval fires on NIST 800-53 and FedRAMP queries where
exact control identifiers (AC-6, IR-4, SC-28) and technical terms
produce distinctive tokens. For AI RMF and AI 600-1 queries, governance
language (govern, measure, trustworthy) does not survive stop word
stripping as useful BM25 anchors — hybrid falls back to dense-only for
these queries. Dense retrieval handles abstract governance language well
through embedding space similarity. The use_hybrid flag allows per-query
tuning in production; current default is hybrid-on for all queries.

**Conversational memory boundary:** Within-session pronoun enrichment implemented —
`enrich_query()` rewrites ambiguous follow-up queries via Bedrock Claude at
temperature=0.0 before retrieval fires (DL-025). Cross-session persistence is the
remaining gap — see Future Work in README.

---

## Evaluation Strategy

RAGAs scores measured at three pipeline stages:

| Stage | Metrics |
|---|---|
| Dense-only baseline | Faithfulness, Context Precision, Context Recall, Answer Relevancy |
| Hybrid retrieval (RRF) | Same metrics — delta vs baseline |
| Hybrid + Cohere rerank | Same metrics — delta vs hybrid |

Score progression table committed to README after Step 8.
Golden dataset: 20-question architect-level Q&A set built after seeing real
retrieval failures in Steps 3–5.
