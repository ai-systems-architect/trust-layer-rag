# Decision Log — governed-compliance-engine

All architectural decisions recorded here. Format: decision made, rationale,
alternatives evaluated. Referenced from config.py via DL-XXX pointers.

---

## DL-001 — Corpus Selection (superseded by DL-011)
*Original decision: NIST SP 800-series + Federal Register API. Refined in
DL-011 after scoping three specific authoritative sources. See DL-011.*

---

## DL-002 — Vector Store
**Decision:** pgvector extension on Amazon RDS (PostgreSQL)
**Date:** 2026-03-31

**Rationale:** Single security boundary — all data (relational metadata,
vector embeddings, audit logs) lives in one RDS instance under one IAM
policy and one VPC. Eliminates a second managed service, a second access
control layer, and a second audit trail. pgvector HNSW index is sufficient
for corpus size (<100K chunks). FedRAMP-aligned deployments prefer fewer
third-party data processors.

**Alternatives evaluated:**
- Pinecone — managed, simple API, excluded: data leaves AWS boundary,
  adds a third-party processor to the compliance surface
- Pinecone — managed, simple API, strong ecosystem, excluded: data leaves
  AWS boundary, adds a third-party processor to the compliance surface;
  strong choice for non-regulated workloads or corpus > 1M vectors where
  pgvector HNSW latency becomes a concern
- Weaviate Cloud — managed, excluded: same third-party boundary concern
  as Pinecone; self-hosted Weaviate viable for air-gapped deployments
- Qdrant Cloud — performant managed vector DB, excluded: data leaves AWS
  boundary; Qdrant self-hosted is a strong alternative to pgvector for
  high-throughput retrieval workloads
- ChromaDB — excluded: no production-grade managed option, local-only
  at this scale
- AWS OpenSearch with k-NN — excluded: heavier operational footprint,
  higher cost for equivalent corpus size
- GCP: AlloyDB with pgvector — equivalent path on GCP; same PostgreSQL
  wire protocol, pgvector supported natively, single security boundary
  preserved; or Vertex AI Vector Search for managed vector DB equivalent
  to Pinecone on GCP
- Azure: Azure Database for PostgreSQL Flexible Server with pgvector —
  direct equivalent; pgvector GA on Azure PostgreSQL as of 2024; or
  Azure AI Search as managed vector DB equivalent to Pinecone on Azure

**Industry context — where each tool fits:**
| Tool | Primary Use Case | Production Signal |
|---|---|---|
| ChromaDB | Prototyping, tutorials | Every RAG tutorial starts here — migrate before production |
| Pinecone | Non-regulated SaaS at scale | Dominant in startups and enterprise SaaS — zero ops |
| Weaviate | Enterprise semantic + structured search | Strong hybrid search — self-hosted for air-gapped |
| Qdrant | Performance-focused workloads | Best-in-class filtering — self-hosted preferred in regulated |
| pgvector | Regulated, single DB boundary | Right tool for federal context — not universal |

**When pgvector is NOT the right choice:**
At 10M+ vectors or sub-10ms P99 latency requirements Qdrant
self-hosted outperforms meaningfully. For non-regulated
production at scale Pinecone removes operational burden
entirely. Provider abstraction layer in this codebase
supports migration to either without application code changes.

---

## DL-003 — Embedding Model
**Decision:** OpenAI text-embedding-3-large (3072 dimensions)
**Date:** 2026-03-31

**Rationale:** 3072-dimensional vectors capture dense regulatory control
language in the NIST/FISMA corpus more precisely than lower-dimensional
alternatives. Regulatory text is highly technical and lexically precise —
higher dimensionality improves separation between semantically similar but
functionally distinct controls (e.g. AC-2 vs AC-3). Provider abstraction
via EMBEDDING_PROVIDER env var means the pipeline is not locked to OpenAI.

**Alternatives evaluated:**
- amazon.titan-embed-text-v2:0 — native Bedrock, no extra API key, 1536
  dims, excluded: lower dimensionality less suited for technical regulatory
  text; remains the swap-in if OpenAI dependency is disallowed
- cohere embed-english-v3.0 — strong retrieval benchmarks, excluded: adds
  a second Cohere dependency alongside re-ranking; OpenAI sufficient for
  English-only NIST corpus
- BGE-M3 (self-hosted) — best open-source option, MIT license, 1024 dims,
  excluded: local GPU infra overhead not warranted at this deployment scale;
  viable for air-gapped FedRAMP HIGH environments
- GCP: text-embedding-004 (Vertex AI) — 768 dims, excluded: lower
  dimensionality; viable if full GCP stack required
- Azure: text-embedding-3-large via Azure OpenAI Service — identical model,
  same dimensions, different API endpoint; drop-in swap via EMBEDDING_PROVIDER

---

## DL-004 — Generation Model
**Decision:** Claude 3.5 Sonnet via Amazon Bedrock (anthropic.claude-3-5-sonnet-20241022-v2:0)
**Date:** 2026-03-31

**Rationale:** Bedrock is the AWS-managed access path to Claude — no direct
Anthropic API key required, IAM-controlled, stays within the AWS security
boundary. Claude 3.5 Sonnet is the best price/performance point for long-
context regulatory summarization and citation-enforced generation. Bedrock
Guardrails integrates natively for PII filtering and hallucination controls
without an additional service.

**Alternatives evaluated:**
- GPT-4o via Azure OpenAI Service — strong alternative, excluded: adds
  Azure dependency to an otherwise AWS-native stack; viable if org is
  Azure-first
- Llama 3 70B via Bedrock — open weights, lower cost, excluded: citation
  enforcement and instruction following weaker than Claude 3.5 Sonnet on
  regulatory text
- Mistral Large via Bedrock — excluded: similar trade-off to Llama; Claude
  Sonnet outperforms on structured compliance output
- GCP: Gemini 1.5 Pro via Vertex AI — strong long-context handling,
  excluded: not in AWS stack; viable if full GCP deployment required;
  equivalent guardrails via Vertex AI Model Armor
- Azure: GPT-4o via Azure OpenAI — direct enterprise path, FedRAMP
  authorized, excluded for same reason as above; preferred choice in
  Azure-first environments

---

## DL-005 — Re-Ranking
**Decision:** Cohere Rerank API (rerank-english-v3.0)
**Date:** 2026-03-31

**Rationale:** Cross-encoder re-ranking improves precision after hybrid
retrieval — dense + sparse fusion returns 10 candidates, Cohere re-ranks
to top 5 before generation. Single API call, no local model hosting,
same cross-encoder quality as self-hosted alternatives. Cohere's rerank
model is purpose-built for retrieval tasks and consistently outperforms
bi-encoder similarity on out-of-distribution regulatory phrasing.

**Alternatives evaluated:**
- Sentence Transformers cross-encoder (self-hosted) — excluded: local GPU
  infra overhead; functionally equivalent but adds operational complexity
- BGE-Reranker-v2-m3 (self-hosted) — excluded: same infra concern;
  best option for air-gapped environments
- Amazon Bedrock — no native rerank API at time of decision; may change
- GCP: Vertex AI Ranking API — managed re-ranking, viable GCP-native
  alternative; same role, different vendor
- Azure: Azure AI Search semantic ranker — built into Azure AI Search,
  excluded: tied to Azure Search as vector store; viable in Azure-first stack

---

## DL-006 — Tracing
**Decision:** Langfuse self-hosted (Docker)
**Date:** 2026-03-31

**Rationale:** Full pipeline observability — every retrieval, re-rank, and
generation call traced end-to-end. Self-hosted means no data leaves the
local environment, no usage-based billing, and no third-party processor
added to the compliance surface. No cost at this deployment scale. Langfuse provides
span-level latency, token counts, and retrieval metadata in a single UI.

**Alternatives evaluated:**
- LangSmith — managed, polished UI, excluded: data leaves local environment,
  usage-based pricing, adds a third-party vendor dependency
- Weights & Biases Weave — strong ML experiment tracking, excluded:
  heavier than needed for pipeline tracing; better fit for model training
- Arize Phoenix — open source, excluded: less mature LangChain integration
  at time of decision
- GCP: Cloud Trace + Vertex AI Experiments — native GCP observability stack,
  viable if full GCP deployment; no single pane for RAG pipeline tracing
- Azure: Azure Monitor + Application Insights — viable in Azure-first stack;
  requires custom instrumentation for RAG span tracking

---

## DL-007 — Chunking Strategy
**Decision:** 600 tokens, 100 token overlap, recursive character splitting
via LangChain's `from_tiktoken_encoder()` with cl100k_base tokenizer
**Date:** 2026-03-31

**Rationale:** 600 tokens (midpoint of 500–800 range) balances regulatory
context retention against retrieval precision. NIST control statements
average 200–400 tokens; 600-token chunks capture a full control plus
surrounding implementation guidance without bleeding into unrelated controls.
100-token overlap preserves cross-chunk continuity for controls that span
paragraph boundaries. Recursive character splitting respects sentence and
paragraph structure before falling back to character-level splits.

tiktoken enforces true token-based boundaries rather than character
approximations — critical for consistency with the OpenAI embedding model
(text-embedding-3-large uses cl100k_base). Character-based approximation
(~4 chars/token) would produce inconsistent chunk sizes across regulatory
text with dense acronyms and control identifiers.

**Alternatives evaluated:**
- Fixed 256-token chunks — too small for regulatory paragraphs; splits
  control statements mid-sentence, breaks retrieval context
- Fixed 1024-token chunks — too large; retrieval returns broad sections
  rather than specific controls, dilutes precision
- Semantic chunking (embedding-based) — excluded: computationally expensive
  at ingestion time, harder to reproduce; revisit if precision degrades
- Markdown/header-aware splitting — excluded: NIST PDFs do not parse to
  clean markdown; recursive character splitting is more robust to PDF
  extraction artifacts
- Character-based approximation (~2,400 chars for 600 tokens) — excluded:
  imprecise for technical regulatory text with dense acronyms; tiktoken
  ensures chunk sizes align exactly with embedding model token limits

---

## DL-008 — Hybrid Retrieval + Thresholds
**Decision:** Dense cosine similarity + BM25 keyword search fused via
Reciprocal Rank Fusion (RRF), top-10 retrieved, re-ranked to top-5
**Date:** 2026-03-31

**Rationale:** Dense retrieval alone misses exact regulatory references —
a query for "AC-2(4)" returns semantically similar controls but not the
exact citation. BM25 catches keyword-precise matches that dense vectors
score weakly. RRF fusion is parameter-free, robust to score scale
differences between dense and sparse, and consistently outperforms
weighted linear combination without requiring tuning. Faithfulness
threshold of 0.85 enforces citation grounding; retrieval precision
threshold of 0.50 flags low-confidence retrievals for review.

**RRF_K=60 — why this value:**
k=60 is the standard default, empirically stable across retrieval benchmarks.
Lower k (e.g. 10) amplifies top-rank differences — brittle when one retriever
dominates. Higher k (e.g. 100) flattens the score distribution — ranks 1 and
10 become nearly indistinguishable. At ~5K chunks, k=60 requires no tuning.

**plainto_tsquery vs to_tsquery:**
to_tsquery() requires manually structured query syntax — to_tsquery('access & management').
Raw user input like "access management controls" throws a syntax error.
plainto_tsquery() tokenizes and ANDs terms automatically — safe for unstructured
compliance queries. websearch_to_tsquery() adds OR/NOT/phrase support but
compliance queries are additive; extra operators introduce noise without
precision gain.

**Alternatives evaluated:**
- Dense-only retrieval — excluded: misses exact control citations; baseline
  benchmark retained in RAGAs evaluation for comparison
- Sparse-only (BM25) — excluded: misses semantic paraphrases of control
  requirements; lower recall on natural language queries
- Weighted linear combination (alpha * dense + (1-alpha) * sparse) —
  excluded: requires tuning alpha per corpus; RRF is parameter-free and
  equally performant
- ColBERT late interaction — excluded: significant infra overhead; best
  option if RRF precision proves insufficient
- GCP: hybrid search in Vertex AI Search — managed hybrid retrieval,
  excluded: vendor-managed fusion, less transparent for portfolio
  demonstration
- Azure: hybrid search in Azure AI Search — BM25 + vector hybrid built-in,
  excluded: ties retrieval to Azure AI Search as vector store

---

## DL-009 — RAG Evaluation Framework
**Decision:** RAGAs
**Date:** 2026-03-31

**Rationale:** Purpose-built for RAG evaluation with the exact metrics
needed for a governed retrieval system — faithfulness measures whether
generated answers are grounded in retrieved chunks, context precision
measures whether retrieval is finding the right passages. Golden dataset
of 50 hand-curated Q&A pairs built from real NIST/FISMA corpus after
basic retrieval working — ensures evaluation reflects actual failure cases
not synthetic queries. Score progression (dense-only vs hybrid+rerank)
documented in README to show iteration.

**Alternatives evaluated:**
- TruLens — good LLM-as-judge approach, excluded: smaller community,
  less established in the RAG evaluation community than RAGAs
- DeepEval — strong CI/CD integration, excluded: more complex setup
  not warranted at this deployment scale
- LangSmith Evals — tight LangChain integration, excluded: data leaves
  self-hosted environment, incompatible with governed federal corpus
  data handling requirements
- Manual spot-check only — excluded: insufficient for portfolio signal,
  RAGAs provides reproducible quantitative benchmark

**Metrics tracked:**
- Faithfulness — are answers grounded in retrieved context
- Context Precision — is retrieval finding the right chunks
- Context Recall — is retrieval finding all relevant chunks
- Answer Relevancy — is the answer relevant to the question

---

## DL-010 — Orchestration Framework
**Decision:** LangChain
**Date:** 2026-03-31

**Rationale:** LangChain provides mature abstractions for every layer of
this pipeline — document loaders, text splitters, embedding wrappers,
retrieval chains, and prompt templates — reducing boilerplate without
sacrificing visibility into pipeline internals. Prompt versioning via
config/prompts.yaml integrates cleanly with LangChain's PromptTemplate
pattern. Strong Langfuse integration via LangChain callbacks means tracing
requires no custom instrumentation.

**Alternatives evaluated:**
- LlamaIndex — strong document indexing abstractions, excluded: retrieval
  pipeline customization (hybrid RRF, custom re-rank step) is more
  transparent in LangChain; LlamaIndex better suited for document-heavy
  RAG without custom retrieval logic
- Google Agent Development Kit (ADK) — Google's framework for building
  multi-agent pipelines, excluded: optimized for Vertex AI and GCP-native
  tooling; adds GCP dependency to an AWS-native stack; strong alternative
  if deploying on GCP with Vertex AI as the model provider
- Custom pipeline (no framework) — excluded: significant boilerplate for
  retrieval chain, prompt management, and callback hooks; framework
  overhead justified at this pipeline complexity
- Haystack — strong enterprise RAG support, excluded: smaller community,
  fewer Bedrock integrations at time of decision

---

## DL-011 — Corpus Selection and FedRAMP Ingestion Challenge
**Decision:** Four sources — NIST SP 800-53 Rev 5, NIST AI RMF 1.0,
NIST AI 600-1 GenAI Profile, FedRAMP Moderate Baseline
**Date:** 2026-03-31

**Corpus sources and direct URLs:**
- NIST SP 800-53 Rev 5 (PDF):
  https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf
- NIST AI RMF 1.0 (PDF):
  https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf
- NIST AI 600-1 GenAI Profile (PDF):
  https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
- FedRAMP Moderate Baseline (Word → PDF):
  https://www.fedramp.gov/assets/resources/templates/SSP-Appendix-A-Moderate-FedRAMP-Security-Controls.docx

**Total corpus:** ~4,900 chunks at 600 tokens — trivial for pgvector
**One-time ingestion cost:** ~$0.70 (OpenAI text-embedding-3-large)
**Live 24/7 cost:** ~$17-20/month (RDS db.t3.micro dominant cost)

**FedRAMP Ingestion Challenge — documented:**
FedRAMP does not publish its Moderate Baseline as a PDF. The authoritative
source is a Word (.docx) template — a heavily formatted SSP appendix with
complex nested tables containing control requirements.

Three options were evaluated:

Option 1 — FedRAMP Transition Guide PDF
  Rejected: Transition guide covers only what changed Rev 4 → Rev 5,
  not the full control catalog. Queries about specific Moderate baseline
  controls (e.g. IR-4, AC-17) would return incomplete context — fails
  the faithfulness gate.

Option 2 — python-docx direct table extraction
  Rejected: python-docx concatenates table cells without structural
  context — control IDs, parameters, and requirements merge into noisy
  unstructured text. Retrieval quality degrades significantly on
  table-heavy government templates.

Option 3 — Download .docx, convert to PDF via LibreOffice (SELECTED)
  Download at ingestion time via requests from direct URL. Convert to
  PDF using LibreOffice headless before parsing. PyMuPDF then handles
  the converted PDF — same parser as all three NIST sources. Pipeline
  remains format-agnostic with zero special cases at parse time.
  LibreOffice preserves table structure in PDF output far more cleanly
  than python-docx text extraction.

**Result:** Single PyMuPDF parser handles all four corpus sources.
python-docx removed from requirements.txt entirely.
LibreOffice required as system dependency — documented in README setup.

**Ingestion order:** 800-53 first to validate full pipeline end to end,
AI RMF second (short, fast validation), AI 600-1 third, FedRAMP last
after retrieval proven on first three sources.

**Alternatives evaluated for corpus scope:**
- 800-53 only — excluded: misses cross-document queries and AI RMF
  portfolio narrative bridge
- FedRAMP Transition Guide — excluded: incomplete control catalog
- Full Federal Register — excluded: millions of documents, scope creep
- Synthetic corpus — excluded: real federal data is the differentiator
- pypdf for PDF parsing — excluded: PyMuPDF produces cleaner text
  extraction on government PDFs, better handling of complex layouts
- pdfplumber — excluded: higher overhead, PyMuPDF sufficient and faster

**Future expansion:** 800-53B control baselines, NIST 800-37 RMF
process guide — additive, zero pipeline changes required

---

## DL-012 — Processed Chunk Storage Format
**Decision:** JSON (data/processed/chunks.json)
**Date:** 2026-04-02

**Rationale:** Chunks are written to JSON after ingestion and read by
embed.py in Step 3. JSON is human-readable — chunks can be inspected,
sampled, and debugged without tooling. Flat list of dicts maps directly
to Python without deserialization overhead. File is written once at
ingest time and read once at embed time — no performance requirement
that would justify a binary format.

**Alternatives evaluated:**
- Pickle — faster serialization, excluded: not human-readable, not
  safe to load from untrusted sources, binary format obscures debugging
- Parquet — columnar, efficient for large datasets, excluded: overkill
  for a one-time read of ~4,900 records; adds pyarrow dependency
- SQLite — queryable, excluded: unnecessary complexity for a linear
  read handoff between two pipeline steps
- Direct in-memory handoff (no file) — excluded: decoupling ingest from
  embed is intentional — embed.py can be re-run independently without
  re-parsing all four source documents

---

## DL-013 — Object Storage
**Decision:** AWS S3, single bucket, raw/ and processed/ prefixes
**Date:** 2026-04-02

**Rationale:** Single bucket with prefix separation keeps one IAM policy,
one access boundary, and one audit trail — same single security boundary
principle as pgvector on RDS. raw/ stores source PDFs as downloaded;
processed/ stores chunks.json after ingestion. Prefixes provide logical
separation without the operational overhead of multiple buckets.
At corpus scale (~4,900 chunks, four PDFs) storage cost is negligible
(<$0.01/month).

**Why single bucket over multiple buckets:**
One IAM policy covers both prefixes. Multi-bucket adds IAM complexity
with no security benefit at this scale. Lifecycle policies and access
controls can be scoped to prefix if needed later.

**Alternatives evaluated:**
- Multiple buckets (one per stage) — excluded: unnecessary IAM overhead,
  no security benefit at this corpus scale
- Local filesystem only — excluded: not reproducible across machines,
  no durability, blocks cloud deployment
- GCP: Google Cloud Storage (GCS) — direct equivalent; single bucket,
  same prefix pattern, IAM via service account; gsutil or google-cloud-storage
  Python client replaces boto3
- Azure: Azure Blob Storage — direct equivalent; single container,
  same prefix pattern, IAM via Managed Identity; azure-storage-blob
  Python client replaces boto3

---

## DL-014 — Infrastructure Provisioning
**Decision:** Terraform
**Date:** 2026-04-02

**Rationale:** Infrastructure as code — RDS and S3 provisioned
reproducibly from a single terraform apply. Version-controlled in git
alongside application code. Tear down and re-provision is deterministic.
start/stop scripts (scripts/rds_start.py, scripts/rds_stop.py) handle
instance lifecycle for cost management — RDS stopped state pauses
instance-hour billing while preserving data and configuration.

**Alternatives evaluated:**
- AWS CDK — Python-native infrastructure code, excluded: AWS-only,
  adds a compile step, heavier than needed for two resources
- AWS SAM — serverless-focused, excluded: wrong fit for RDS + S3,
  designed for Lambda deployments
- Pulumi — code-first like CDK, supports multiple clouds, excluded:
  smaller ecosystem than Terraform, less portfolio recognition
- Manual AWS Console — excluded: not reproducible, nothing to show
  in portfolio, error-prone across environments
- GCP: Terraform same AWS provider swapped for google provider —
  identical workflow; or Google Cloud Deployment Manager as native
  GCP alternative
- Azure: Terraform same workflow with azurerm provider — identical
  workflow; or Azure Bicep as native Azure IaC alternative

---

## DL-015 — Network Architecture and RDS Access Pattern
**Decision:** Default VPC, public RDS, SSL enforced, no dedicated VPC
**Date:** 2026-04-02

**Rationale:** Streamlit Community Cloud runs on GCP us-central1 —
outside AWS entirely. RDS must accept connections from public internet
regardless of VPC configuration. Dedicated VPC with public RDS adds
Terraform complexity with zero security benefit over default VPC with
public RDS — same exposure, more code. SSL enforced at parameter group
level (rds.force_ssl=1) and strong generated password are the security
layer. Corpus is public NIST documents — no sensitive data at risk.
RDS down when not in use further minimizes exposure.

**Why not dedicated VPC:**
Dedicated VPC only provides security benefit when application layer
is also inside AWS — RDS in private subnet, app in same VPC, no
public endpoint needed. Streamlit Community Cloud on GCP breaks
this model entirely. Dedicated VPC with public RDS = same security
posture as default VPC with public RDS, with more Terraform overhead.

**Why not IP restriction:**
Streamlit Community Cloud uses GCP shared IP ranges — broad CIDR
blocks not guaranteed stable. Whitelisting GCP ranges effectively
opens RDS to large portions of internet. Developer IP changes across
networks. IP restriction creates access friction for interviews
without meaningful security improvement.

**Security controls in place:**
- SSL enforced — rds.force_ssl=1 at parameter group level
- Strong 32-character randomly generated password in .env
- RDS powered down when not actively used
- Public NIST corpus — no PII, no sensitive data

**Production pattern documented in docs/architecture.md**

---

## DL-016 — Ingestion Pipeline Compute (Production Recommendation)
**Decision:** AWS Batch recommended for production. Not implemented — pipeline runs locally during development.
**Date:** 2026-04-02

**Rationale:** Ingestion is periodic and maintenance-only (re-run when corpus
updates). No persistent compute infrastructure justified. AWS Batch provides
ephemeral containers on-demand, job queue, pay-per-runtime — right fit for
a pipeline that runs once per corpus update cycle.

| Option | Verdict | Reason |
|--------|---------|--------|
| AWS Batch | ✅ Recommended | Ephemeral containers, job queue, pay-per-runtime, right fit for periodic pipelines |
| ECS Fargate tasks | Viable | Same pattern, slightly less ergonomic for batch; good if already operating ECS |
| Step Functions | Extension | Orchestration layer over Batch — adds per-step retry and error handling |
| Lambda | ❌ Rejected | 15-min timeout, 10GB memory ceiling — insufficient for full corpus embedding |
| EC2 persistent | ❌ Rejected | Idle cost between runs, unnecessary attack surface |
| EKS | ❌ Rejected | Operational overhead unjustified for periodic job with no scaling requirement |
| GCP equivalent | — | Cloud Run Jobs |
| Azure equivalent | — | Azure Container Apps Jobs or Azure Batch |

**Step Functions as natural extension:**
Chain download → parse → embed as discrete Steps with per-step retry
and error handling. Each stage retries independently — failed embed
step does not re-download corpus. Adds ~50 lines of Terraform over
a raw Batch job definition.
