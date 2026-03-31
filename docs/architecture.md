# Architecture — governed-compliance-engine

High-level system design. For why each component was chosen over alternatives,
see docs/decision_log.md.

---

## Overview

Governed RAG system for NIST, FISMA, and FedRAMP compliance. Ingests federal
regulatory PDFs and Federal Register API data, stores embeddings in pgvector,
retrieves via hybrid dense + sparse fusion, re-ranks with Cohere, generates
citation-enforced responses via Claude 3.5 Sonnet on Bedrock, and enforces
hallucination controls via Bedrock Guardrails. Every pipeline call is traced
end-to-end in self-hosted Langfuse.

---

## Pipeline

```
PDF / Federal Register API
        │
        ▼
   Document Ingestion
   (LangChain loaders + recursive character splitting)
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
| Ingestion | LangChain PDF loader + Federal Register API | Parse and chunk regulatory documents |
| Embedding | OpenAI text-embedding-3-large | 3072-dim dense vectors |
| Vector Store | pgvector on Amazon RDS | HNSW index, cosine similarity, single security boundary |
| Retrieval | pgvector (dense) + tsvector (sparse) + RRF | Hybrid fusion — exact citations + semantic queries |
| Re-ranking | Cohere rerank-english-v3.0 | Cross-encoder precision over top-10 candidates |
| Generation | Claude 3.5 Sonnet via Amazon Bedrock | Citation-enforced regulatory responses |
| Guardrails | Amazon Bedrock Guardrails | PII filtering + hallucination controls |
| Tracing | Langfuse (self-hosted, Docker) | End-to-end pipeline observability |
| Evaluation | RAGAs | Faithfulness + retrieval precision scoring |
| Frontend | Streamlit | Chat UI + debug sidebar |
| Infrastructure | Terraform + Amazon RDS + S3 | Provisioning and storage |

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
| Amazon Bedrock (Claude) | Vertex AI + Claude via Vertex Model Garden |
| Amazon Bedrock Guardrails | Vertex AI Model Armor |
| OpenAI Embeddings | Vertex AI text-embedding-004 (or keep OpenAI) |
| Cohere Rerank | Vertex AI Ranking API |
| LangChain orchestration | Google Agent Development Kit (ADK) — GCP-native alternative |
| Amazon S3 | Google Cloud Storage |
| AWS IAM | GCP IAM + Workload Identity |
| Langfuse (self-hosted) | Langfuse (self-hosted — cloud-agnostic) |

### Azure Stack

| AWS Component | Azure Equivalent |
|---|---|
| Amazon RDS + pgvector | Azure Database for PostgreSQL Flexible Server + pgvector |
| Amazon Bedrock (Claude) | Azure AI Foundry + Claude via Azure Marketplace |
| Amazon Bedrock Guardrails | Azure AI Content Safety |
| OpenAI Embeddings | Azure OpenAI Service (text-embedding-3-large — identical model) |
| Cohere Rerank | Azure AI Search semantic ranker |
| LangChain orchestration | LangChain (cloud-agnostic) or Azure AI Agent Service |
| Amazon S3 | Azure Blob Storage |
| AWS IAM | Azure Managed Identity + RBAC |
| Langfuse (self-hosted) | Langfuse (self-hosted — cloud-agnostic) |

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
