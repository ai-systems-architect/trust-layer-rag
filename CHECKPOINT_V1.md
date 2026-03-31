# Project Checkpoint — governed-compliance-engine
**Date:** 2026-03-31
**Repo:** https://github.com/ai-systems-architect/governed-compliance-engine
**Status:** Project start — scaffold only

---

## Project Identity

**Name:** `governed-compliance-engine`
**Tagline:** Governed RAG system for NIST, FISMA, and FedRAMP compliance — hybrid retrieval, hallucination controls, and full pipeline observability.
**Portfolio Position:** P2 of 4 — follows `responsible-mlops-risk-engine`

---

## Environment

- GitHub org: `ai-systems-architect` (free plan)
- Repo: `governed-compliance-engine` (private until ready)
- Python 3.9.6 — virtual environment at `~/governed-compliance-engine/venv`
- AWS CLI configured and connected
- `export PYTHONPATH=.` required when running scripts locally

---

## Target Architecture

| Layer | Component | Tool |
|---|---|---|
| Ingestion | PDF + API parsing, chunking | LangChain text splitters |
| Embedding | Dense vectors | Bedrock Titan Embeddings |
| Vector Store | pgvector + HNSW index | RDS PostgreSQL |
| Retrieval | Dense + sparse fused via RRF | pgvector + tsvector |
| Re-ranking | Cross-encoder re-rank | Cohere Rerank API |
| Tracing | Full pipeline observability | Langfuse (Docker) |
| Generation | Citation-enforced prompts | LangChain + Bedrock Claude |
| Guardrails | PII + hallucination controls | Bedrock Guardrails |
| Evaluation | Golden dataset scoring | RAGAs |
| Frontend | Chat UI + debug sidebar | Streamlit Community Cloud |
| Infrastructure | RDS, S3, Bedrock IAM | Terraform |

---

## Implementation Steps

| Step | Description | LOE | Status |
|---|---|---|---|
| 1 | Project Scaffold & Infrastructure | 4–6 hrs | ⬜ Pending |
| 2 | Document Ingestion Pipeline | 6–8 hrs | ⬜ Pending |
| 3 | Embedding & pgvector Store | 5–7 hrs | ⬜ Pending |
| 4 | Hybrid Retrieval | 6–8 hrs | ⬜ Pending |
| 5 | Cohere Re-Ranker | 2–3 hrs | ⬜ Pending |
| 6 | Langfuse Tracing | 4–5 hrs | ⬜ Pending |
| 7 | Generation + Bedrock Guardrails + prompt versioning | 7–9 hrs | ⬜ Pending |
| 8 | RAGAs Evaluation + golden dataset + score progression table | 9–11 hrs | ⬜ Pending |
| 9 | Streamlit Frontend + Streamlit Community Cloud deploy + DEMO.md | 6–8 hrs | ⬜ Pending |
| 10 | Documentation & Decision Log | 3–4 hrs | ⬜ Pending |

**Total LOE:** 52–69 hours

**Build order is fixed:**
1→2→3 → 6 (Langfuse before generation) → 4→5→7 → 8 (after real failures visible) → 9→10

---

## Files to Commit at Scaffold

| File | Purpose |
|---|---|
| `config.py` | Central pipeline config — no hardcoded values |
| `config/prompts.yaml` | Prompt templates versioned in git from day one |
| `.env.example` | Environment variable template |
| `docs/decision_log.md` | DL-001 onwards |
| `requirements.txt` | All pipeline dependencies |
| `.github/workflows/ci.yml` | Lint + structure validation |
| `CHECKPOINT_V1.md` | This file |
| `README.md` | Repo identity + tagline |

---

## Key Decisions Already Made (Pre-Build)

| # | Decision | Rationale |
|---|---|---|
| DL-001 | NIST + Federal Register as corpus | Real federal data — authoritative, public, no synthetic data |
| DL-002 | pgvector on RDS over dedicated vector DB | Single security boundary, one IAM policy, one audit trail |
| DL-003 | Hybrid retrieval — dense + BM25 via RRF | Dense misses exact regulatory references; sparse catches keyword precision |
| DL-004 | Cohere Rerank over Sentence Transformers | Single API call, no local infra, same cross-encoder quality |
| DL-005 | Langfuse self-hosted over LangSmith | Free, no data leaves local environment, full trace visibility |
| DL-006 | Chunk size 500–800 tokens, 100 overlap | Balances regulatory context retention vs retrieval precision |
| DL-007 | Prompt versioning in config/prompts.yaml | Prompts treated as architecture — versioned, traceable, reproducible |
| DL-008 | 50-pair golden dataset | Achievable, meaningful — built after seeing real retrieval failures |

---

## Configuration (Placeholders — Update in .env)

| Parameter | Value | Location |
|---|---|---|
| `CORPUS_SOURCES` | NIST, Federal Register | config.py |
| `CHUNK_SIZE` | 500–800 tokens | config.py |
| `CHUNK_OVERLAP` | 100 tokens | config.py |
| `EMBEDDING_MODEL` | amazon.titan-embed-text-v1 | config.py |
| `RERANK_MODEL` | rerank-english-v3.0 | config.py |
| `FAITHFULNESS_THRESHOLD` | 0.85 | config.py |
| `RETRIEVAL_PRECISION_THRESHOLD` | 0.50 | config.py |
| `AWS_ACCOUNT_ID` | set | .env |
| `S3_BUCKET` | placeholder | .env |
| `RDS_ENDPOINT` | placeholder | .env |
| `COHERE_API_KEY` | placeholder | .env |
| `BEDROCK_GUARDRAIL_ID` | placeholder | .env |

---

## 10/10 Portfolio Additions (Wired Into Steps)

| Addition | Step | Action |
|---|---|---|
| Prompt version history | Step 7 | Two prompt versions committed to git + decision log entry |
| RAGAs score progression | Step 8 | Dense-only vs hybrid+rerank table in README |
| Live demo | Step 9 | Deploy to Streamlit Community Cloud + DEMO.md with 5–10 sample queries |

---

## Cost Tracking

| Phase | Estimated Cost |
|---|---|
| Development (RDS + Bedrock + Cohere) | $15–30 total |
| Demo (RDS t3.micro + Bedrock per query) | ~$15/month |
| Langfuse, Streamlit Community Cloud | $0 |

- RDS: tear down when not working (~$2/day dev, ~$0.50/day demo)
- Spin up same day for interviews

---

## Pending

| Item | Notes |
|---|---|
| Create GitHub repo | `governed-compliance-engine` under `ai-systems-architect` org |
| Initialize repo structure | Mirror `responsible-mlops-risk-engine` scaffold pattern |
| Update .env | All placeholders need real values before Step 2 |
| Provision RDS | Terraform Step 1 — tear down same day if not building |
