# governed-compliance-engine

Governed RAG system for NIST, FISMA, and FedRAMP compliance — hybrid retrieval,
hallucination controls, and full pipeline observability.

**Portfolio:** P2 of 4 — follows [responsible-mlops-risk-engine](https://github.com/ai-systems-architect/responsible-mlops-risk-engine)

---

## Architecture

| Layer | Component | Tool |
|---|---|---|
| Ingestion | PDF + Word parsing, chunking | PyMuPDF + python-docx |
| Embedding | Dense vectors (3072 dims) | OpenAI text-embedding-3-large |
| Vector Store | pgvector + HNSW index | RDS PostgreSQL |
| Retrieval | Dense + sparse fused via RRF | pgvector + tsvector |
| Re-ranking | Cross-encoder re-rank | Cohere rerank-english-v3.0 |
| Tracing | Full pipeline observability | Langfuse (self-hosted) |
| Generation | Citation-enforced prompts | Claude 3.5 Sonnet via Bedrock |
| Guardrails | PII + hallucination controls | Bedrock Guardrails |
| Evaluation | Golden dataset scoring | RAGAs |
| Frontend | Chat UI + debug sidebar | Streamlit |
| Infrastructure | RDS, S3, IAM | Terraform + AWS |

Full rationale for each component: [docs/decision_log.md](docs/decision_log.md)
Cloud equivalents (GCP, Azure): [docs/architecture.md](docs/architecture.md)

---

## Corpus

Four authoritative federal sources — no synthetic data.

| Source | Format | Chunks | Purpose |
|---|---|---|---|
| NIST SP 800-53 Rev 5 | PDF | ~3,000 | Master federal security control catalog |
| NIST AI RMF 1.0 | PDF | ~400 | AI risk management — bridges to P1 portfolio project |
| NIST AI 600-1 GenAI Profile | PDF | ~300 | AI-specific risk and trustworthiness guidance |
| FedRAMP Moderate Baseline | Word | ~1,200 | Maps 800-53 controls to cloud authorization requirements |

Total: ~4,900 chunks — one-time ingestion cost ~$0.70 (OpenAI embeddings)

---

## Build Progress

| Step | Description | Status |
|---|---|---|
| 1 | Project Scaffold & Infrastructure | In Progress |
| 2 | Document Ingestion Pipeline | Pending |
| 3 | Embedding & pgvector Store | Pending |
| 4 | Hybrid Retrieval | Pending |
| 5 | Cohere Re-Ranker | Pending |
| 6 | Langfuse Tracing | Pending |
| 7 | Generation + Bedrock Guardrails + prompt versioning | Pending |
| 8 | RAGAs Evaluation + golden dataset + score progression | Pending |
| 9 | Streamlit Frontend + demo deploy | Pending |
| 10 | Documentation & Decision Log | Pending |

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
- Docker (for Langfuse)
- PostgreSQL RDS instance with pgvector extension (provisioned via Terraform in Step 1)

---

## RAGAs Score Progression

*Populated after Step 8 — dense-only baseline vs hybrid+rerank delta.*

| Pipeline Stage | Faithfulness | Context Precision | Context Recall | Answer Relevancy |
|---|---|---|---|---|
| Dense-only baseline | — | — | — | — |
| Hybrid retrieval (RRF) | — | — | — | — |
| Hybrid + Cohere rerank | — | — | — | — |

---

## Cost

| Component | Cost |
|---|---|
| One-time ingestion (OpenAI embeddings) | ~$0.70 |
| Development (RDS + Bedrock + Cohere) | ~$15–30 total |
| Live demo (RDS t3.micro + Bedrock per query) | ~$17–20/month |
| Langfuse, Streamlit Community Cloud | $0 |

RDS is provisioned on demand — tear down when not actively building (~$2/day active).
