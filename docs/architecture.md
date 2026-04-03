# Architecture — governed-compliance-engine

High-level system design. For why each component was chosen over alternatives,
see docs/decision_log.md.

---

## Overview

Governed RAG system for NIST, FISMA, and FedRAMP compliance. Ingests four
federal regulatory documents (three PDFs via PyMuPDF, FedRAMP Word document
converted to PDF via LibreOffice), stores embeddings in pgvector on RDS,
retrieves via hybrid dense + sparse fusion, re-ranks with Cohere, generates
citation-enforced responses via Claude 3.5 Sonnet on Bedrock, and enforces
hallucination controls via Bedrock Guardrails. Every pipeline call is traced
end-to-end in self-hosted Langfuse.

---

## Pipeline

```
NIST 800-53 / AI RMF / AI 600-1 (PDF) + FedRAMP Moderate (.docx → PDF)
        │
        ▼
   Document Ingestion
   (PyMuPDF extraction + tiktoken chunking)
   [production: AWS Batch job — see DL-016]
        │
        ▼
   Embedding
   (OpenAI text-embedding-3-large — 3072 dims)
        │
        ▼
   pgvector on RDS
   (HNSW index — cosine similarity)
        │
   ┌────┴────┐
   │         │
Dense       Sparse
(pgvector)  (tsvector / BM25)
   │         │
   └────┬────┘
        │  RRF fusion (top-10)
        ▼
   Cohere Rerank (top-5)
        │
        ▼
   Generation
   (Claude 3.5 Sonnet via Bedrock + Bedrock Guardrails)
        │
        ▼
   Langfuse Tracing
   (span-level: retrieval → rerank → generation)
```

---

## Component Stack

| Layer | Component | Purpose |
|---|---|---|
| Ingestion | PyMuPDF + LibreOffice (FedRAMP conversion) | Parse and chunk four federal regulatory documents |
| Embedding | OpenAI text-embedding-3-large | 3072-dim dense vectors |
| Vector Store | pgvector on Amazon RDS | HNSW index, cosine similarity, single security boundary |
| Retrieval | pgvector (dense) + tsvector (sparse) + RRF | Hybrid fusion — exact citations + semantic queries |
| Re-ranking | Cohere rerank-english-v3.0 | Cross-encoder precision over top-10 candidates |
| Generation | Claude 3.5 Sonnet via Amazon Bedrock | Citation-enforced regulatory responses |
| Guardrails | Amazon Bedrock Guardrails | PII filtering + hallucination controls |
| Tracing | Langfuse (self-hosted, Docker) | End-to-end pipeline observability |
| Evaluation | RAGAs | Faithfulness + retrieval precision scoring |
| Frontend | Streamlit | Chat UI + debug sidebar |
| Object Storage | Amazon S3 | Raw PDFs (raw/) + processed chunks (processed/) |
| Infrastructure | Terraform + scripts/rds_start.py + scripts/rds_stop.py | Provisioning, RDS lifecycle management |

---

## Security Boundary

All data at rest and in transit stays within the AWS VPC. RDS is not
publicly accessible — application layer connects via VPC private subnet.
IAM roles control Bedrock and S3 access. No embeddings or document chunks
leave the AWS environment. Langfuse runs locally — traces do not leave
the development machine.

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
| Langfuse (self-hosted) | Langfuse (self-hosted — cloud-agnostic) |

### Azure Stack

| AWS Component | Azure Equivalent |
|---|---|
| Amazon RDS + pgvector | Azure Database for PostgreSQL Flexible Server + pgvector |
| pgvector (managed vector DB alternative) | Azure AI Search — managed, Pinecone-equivalent on Azure |
| Amazon Bedrock (Claude) | Azure AI Foundry + Claude via Azure Marketplace |
| Amazon Bedrock Guardrails | Azure AI Content Safety |
| OpenAI Embeddings | Azure OpenAI Service (text-embedding-3-large — identical model) |
| Cohere Rerank | Azure AI Search semantic ranker |
| LangChain orchestration | LangChain (cloud-agnostic) or Azure AI Agent Service |
| Amazon S3 | Azure Blob Storage — single container, same prefix pattern |
| AWS IAM | Azure Managed Identity + RBAC |
| Terraform | Terraform (azurerm provider) or Azure Bicep |
| Langfuse (self-hosted) | Langfuse (self-hosted — cloud-agnostic) |

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

---

## Evaluation Strategy

RAGAs scores measured at three pipeline stages:

| Stage | Metrics |
|---|---|
| Dense-only baseline | Faithfulness, Context Precision, Context Recall, Answer Relevancy |
| Hybrid retrieval (RRF) | Same metrics — delta vs baseline |
| Hybrid + Cohere rerank | Same metrics — delta vs hybrid |

Score progression table committed to README after Step 8.
Golden dataset: 50 hand-curated Q&A pairs built after seeing real
retrieval failures in Steps 3–5.
