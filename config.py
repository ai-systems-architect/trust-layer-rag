import os
from dotenv import load_dotenv

load_dotenv()

# AWS
# see docs/decision_log.md DL-001
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCOUNT_ID = os.getenv("AWS_ACCOUNT_ID")

# S3
S3_BUCKET = os.getenv("S3_BUCKET")

# RDS / pgvector
# see docs/decision_log.md DL-002
RDS_ENDPOINT = os.getenv("RDS_ENDPOINT")
RDS_PORT = int(os.getenv("RDS_PORT", "5432"))
RDS_DB_NAME = os.getenv("RDS_DB_NAME", "compliance")
RDS_USER = os.getenv("RDS_USER")
RDS_PASSWORD = os.getenv("RDS_PASSWORD")

# Embedding — OpenAI text-embedding-3-large (3072 dims)
# see docs/decision_log.md DL-003
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "openai")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", "3072"))

# Generation — Claude 3.5 Sonnet via Bedrock
# see docs/decision_log.md DL-004
GENERATION_PROVIDER = os.getenv("GENERATION_PROVIDER", "bedrock")
GENERATION_MODEL = os.getenv("GENERATION_MODEL", "anthropic.claude-3-5-sonnet-20241022-v2:0")
BEDROCK_GUARDRAIL_ID = os.getenv("BEDROCK_GUARDRAIL_ID")

# Cohere — re-ranking only
# see docs/decision_log.md DL-005
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
RERANK_MODEL = os.getenv("RERANK_MODEL", "rerank-english-v3.0")

# Langfuse — self-hosted tracing
# see docs/decision_log.md DL-006
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://localhost:3000")

# Chunking
# see docs/decision_log.md DL-007
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "600"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# Retrieval
# see docs/decision_log.md DL-008
FAITHFULNESS_THRESHOLD = float(os.getenv("FAITHFULNESS_THRESHOLD", "0.85"))
RETRIEVAL_PRECISION_THRESHOLD = float(os.getenv("RETRIEVAL_PRECISION_THRESHOLD", "0.50"))
TOP_K_RETRIEVAL = int(os.getenv("TOP_K_RETRIEVAL", "10"))
TOP_K_RERANK = int(os.getenv("TOP_K_RERANK", "5"))

# =============================================================================
# CORPUS CONFIGURATION
# Decision: Four authoritative federal sources — NIST 800-53, AI RMF,
#            AI 600-1, FedRAMP Moderate Baseline
# Rationale: 800-53 is the master control catalog (~3,000 chunks). AI RMF
#            bridges to P1 responsible-mlops-risk-engine portfolio narrative
#            (~400 chunks). AI 600-1 GenAI Profile adds AI-specific risk
#            coverage (~300 chunks). FedRAMP enables cross-document queries
#            mapping controls to cloud authorization baselines (~1,200 chunks).
#            Total ~4,900 chunks — trivial for pgvector, negligible cost.
# Parsers: PyMuPDF for PDFs (.pdf), python-docx for Word (.docx)
# Ingestion order: 800-53 first (validate pipeline), AI RMF second,
#            AI 600-1 third, FedRAMP last (after retrieval proven)
# One-time ingestion cost: ~$0.70 total (OpenAI embeddings)
# Decision rationale: see docs/decision_log.md DL-011
# =============================================================================
CORPUS_SOURCES = os.getenv(
    "CORPUS_SOURCES",
    "nist_800_53,nist_ai_rmf,nist_ai_600_1,fedramp_moderate_baseline"
).split(",")

# All PDF sources served from nvlpubs.nist.gov — NIST's canonical publication server
NIST_800_53_URL = os.getenv(
    "NIST_800_53_URL",
    "https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf"
)
NIST_AI_RMF_URL = os.getenv(
    "NIST_AI_RMF_URL",
    "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf"
)
NIST_AI_600_1_URL = os.getenv(
    "NIST_AI_600_1_URL",
    "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf"
)
FEDRAMP_BASELINE_URL = os.getenv(
    "FEDRAMP_BASELINE_URL",
    "https://www.fedramp.gov/rev5/documents-templates/"
)

S3_RAW_PREFIX = os.getenv("S3_RAW_PREFIX", "raw/")
S3_PROCESSED_PREFIX = os.getenv("S3_PROCESSED_PREFIX", "processed/")
