# Evaluation Methodology — The Trust Layer for Federal Compliance AI

Three independent evaluation layers assess different concerns:

- **RAGAs evaluation** — measures end-to-end answer quality after generation
- **Retrieval diagnostics** — measures retrieval quality before generation runs
- **Adversarial guardrail evaluation** — verifies correct refusal behavior on out-of-scope and unanswerable queries; implemented in `evaluation/guardrail_test.py`

These are separate questions. A retriever can surface the right chunks while the
generator still produces a poorly-grounded answer; both can perform well while the
system still fails to refuse out-of-scope queries correctly. All three layers are
needed for a complete picture.

---

## Part 1 — RAGAs Evaluation

### What it measures

RAGAs evaluates the full pipeline output — whether the final generated answer is
faithful to the retrieved context, and whether the retrieved context is relevant and
sufficient to answer the question. Generation behavior is in scope.

### Metrics

**Faithfulness** — are the claims in the generated answer supported by the retrieved
chunks? Measures hallucination. Primary signal for a federal compliance system — an
answer that invents control requirements is worse than no answer.
Target: ≥ 0.75. Actual: 0.90 (semantic), 0.89 (hybrid).

**Context Precision** — are the top-ranked retrieved chunks relevant to the question?
Measures ranking quality of the retriever. High context precision means Claude receives
high-quality input, which directly supports faithfulness.
Target: ≥ 0.65. Actual: 0.94 (semantic), 0.95 (hybrid).

**Context Recall** — does the retrieved context cover the information needed to answer
the question? Measures breadth of retrieval. Complements context precision — high
precision with low recall means the few chunks returned are good but the full answer
requires chunks that were not retrieved.
Target: ≥ 0.60. Actual: 0.75 (semantic), 0.76 (hybrid).

**Answer Relevancy** — does the answer address the question that was asked? Measured
by generating a synthetic question from the answer and comparing it to the original.
Penalizes off-topic or over-hedged answers.
Target: ≥ 0.70. Actual: 0.56 (semantic), 0.51 (hybrid) — below target, documented.

### Why answer relevancy is below target (by design)

Two systematic causes, neither fixable without reducing system integrity:

1. The system prompt instructs Claude to hedge compliance assertions and note
   applicability limitations. RAGAs rewards direct concise answers and penalizes
   qualifying language. Conservative compliance behavior is correct for this use
   case but scores lower on this metric by design.

2. Golden dataset questions are architect-level multi-part queries. RAGAs synthetic
   question generation fragments on multi-part questions, producing synthetic questions
   that only partially overlap with the original. This is a known limitation of the
   metric for complex evaluation sets.

Faithfulness (0.90) and context precision (0.94) are the primary signals. Answer
relevancy was not tuned — optimizing for it would require weakening safety behavior.

### RAGAs metric selection rationale

For a federal compliance RAG system, the failure mode hierarchy is:

1. **Worst**: answer fabricates or misrepresents control requirements → faithfulness
2. **Bad**: right answer built from wrong chunks → context precision
3. **Moderate**: incomplete answer because relevant chunks were not retrieved → context recall
4. **Acceptable**: answer is correct but phrased more cautiously than the question expected → answer relevancy

This ordering drives metric priority. Faithfulness and context precision are the
gates — context recall and answer relevancy are secondary quality signals.

### Why Answer Correctness was not measured

RAGAs ships an Answer Correctness metric that compares the generated answer
to a reference answer using LLM-as-judge. It is deliberately excluded from
this evaluation for two reasons.

First, for a federal compliance corpus, the source-of-truth is the corpus
itself, not the evaluator's reference answer. The reference answers in the
golden dataset were synthesized for chunk-labeling purposes (Option A token
Jaccard overlap with retrieved candidates) — they are useful as ground
truth for retrieval evaluation but treating them as the canonical correct
response assumes a single right answer exists. NIST text often supports
multiple defensible interpretations of the same control. Faithfulness
(does the answer match the retrieved chunks?) is a stronger correctness
signal than reference-match (does the answer match the answer the
evaluator wrote?) because it measures grounding in authoritative source
material rather than grounding in the evaluator's prior expectation.

Second, RAGAs Answer Correctness is LLM-as-judge over two free-text
answers — a noisy, expensive metric that the RAGAs documentation itself
flags as less reliable than the retrieval-grounded metrics. Faithfulness
(0.90 / 0.89), Context Precision (0.94 / 0.95), and Context Recall
(0.75 / 0.76) collectively cover what a reliable Correctness metric
would measure for a governed-domain RAG system: that the answer is
grounded in retrieved chunks, that the retrieved chunks are relevant,
and that the retrieval covered enough of the corpus to support the
answer. Adding Answer Correctness on top of these would not change
which architectural decisions are defensible — it would add cost
without adding signal.

Equivalent metric in standard RAG evaluation tutorials (e.g., LangSmith's
four-metric framework — Correctness / Relevance / Groundedness /
Retrieval Relevance) is therefore mapped to Faithfulness in this
evaluation. Three of the four LangSmith metrics map directly onto RAGAs
metrics measured here; the fourth is replaced by the stronger signal.

---

## Part 2 — Retrieval Diagnostics

### What it measures

Retrieval diagnostics evaluate retriever quality independently of generation.
The question: given that the correct chunks exist in the corpus, is the retriever
finding them and ranking them at the top? Generation behavior is not in scope.

Three pipeline configurations are compared:

| Configuration | Description |
|---------------|-------------|
| Semantic | Dense pgvector HNSW cosine similarity, top-10 |
| Hybrid | Dense + BM25 (tsvector) + RRF fusion, top-10 |
| Hybrid + Rerank | Hybrid top-10 → Cohere cross-encoder, top-5 |

### Ground truth labeling methodology

Each golden dataset question requires a set of `relevant_chunk_ids` — the chunk IDs
the retriever should return. Labels are derived automatically (Option A):

1. Run broad retrieval: semantic top-30 + BM25 top-30 per question, deduplicated
2. For each candidate chunk, compute token Jaccard overlap with the reference answer
3. Chunks with overlap ≥ threshold labeled as relevant
4. For control ID queries: any chunk containing the explicit identifier (AC-6, AU-2)
   is labeled relevant regardless of overlap score

**Labeling limitation:** Labels derived from semantic similarity to `reference_answer`.
Semantic Recall@k may be slightly optimistic — the label pool was seeded from the same
embedding space. Hybrid and rerank improvements *relative to* semantic are honest
comparisons between configurations and remain valid architectural signals.

Manual labeling would eliminate this bias but requires approximately two hours of
annotator time. Auto-labeling is the correct starting point for a portfolio evaluation.

### Metrics

#### Recall@k

What fraction of known relevant chunks appear in the top-k retrieved results?

```
Recall@k = |relevant chunks in top-k| / |total relevant chunks for question|
```

Averaged across all questions.

**Example:** AC-6 question has 3 relevant chunks in corpus. Top-5 retrieval returns 2.
Recall@5 = 2/3 = 0.67.

#### MRR (Mean Reciprocal Rank)

Where does the first relevant chunk appear in the ranked list?

```
MRR = (1 / |Q|) × Σ (1 / rank of first relevant chunk)
```

If no relevant chunk appears in top-k, that question contributes 0.

**Example across 3 questions:**
- Q1: first relevant chunk at rank 1 → 1/1 = 1.00
- Q2: first relevant chunk at rank 2 → 1/2 = 0.50
- Q3: first relevant chunk at rank 4 → 1/4 = 0.25
- MRR = (1.00 + 0.50 + 0.25) / 3 = 0.58

MRR answers: "Is the most relevant chunk bubbling to the top or getting buried?"
MRR Semantic, MRR Hybrid, and MRR Hybrid+Rerank are all three required columns.
MRR Hybrid (before reranking) isolates what BM25 fusion contributes to rank position
independently of what Cohere does on top.

**Architectural signal:** If MRR jumps mainly at Semantic → Hybrid, RRF fusion is
doing most of the ranking work. If MRR jumps mainly at Hybrid → Hybrid+Rerank, Cohere
is where ranking quality comes from. Both are valid outcomes with different implications
for production cost optimization.

#### nDCG (Normalized Discounted Cumulative Gain)

Rewards both finding relevant chunks and ranking them earlier. Accounts for multiple
relevant chunks at different positions — more nuanced than MRR.

```
DCG@k  = Σ (rel_i / log₂(i + 1))   for i = 1 to k
nDCG@k = DCG@k / IDCG@k
```

IDCG is the ideal DCG — what DCG would be if all relevant chunks were ranked first.
nDCG = 1.0 means perfect ranking. nDCG = 0.0 means no relevant chunks retrieved.

### Query type classification

Questions are grouped by type to show where each retrieval configuration adds value:

| Type | Questions | Source | Characteristic |
|------|-----------|--------|----------------|
| Control ID | IDs 1–5, 14–17 | NIST 800-53, FedRAMP | Explicit control identifiers (AC-6, AU-2, IR-4, SC-8, CM-7) — BM25 should fire |
| Governance | IDs 6–13 | NIST AI RMF, NIST AI 600-1 | Abstract governance language — dense retrieval expected to dominate |
| Cross-corpus | IDs 18–20 | Cross-corpus | Spans multiple sources — hybrid and rerank expected to help most |

### Results table structure

| Query Type | R@5 Semantic | R@5 Hybrid | R@5 H+Rerank | MRR Semantic | MRR Hybrid | MRR H+Rerank |
|---|---|---|---|---|---|---|
| Control ID (n=9) | 0.1516 | 0.1558 | 0.1558 | 1.0000 | 1.0000 | 1.0000 |
| Governance (n=8) | 0.2099 | 0.2099 | 0.2197 | 0.8750 | 0.9375 | 0.9375 |
| Cross-corpus (n=3) | 0.1130 | 0.1258 | 0.1258 | 0.6667 | 0.6667 | 0.6667 |
| **Average (n=20)** | **0.1691** | **0.1729** | **0.1768** | **0.9000** | **0.9250** | **0.9250** |

nDCG@5 — Semantic: 0.8883 | Hybrid: 0.9092 | Hybrid+Rerank: 0.9265

nDCG@5 is reported as a single average across all 20 questions rather than
broken out by query type. nDCG's logarithmic rank-position weighting makes
it more sensitive to small sample sizes than Recall@5 or MRR — at n=3 for
cross-corpus and n=8–9 for the other types, segment-level nDCG numbers
would reflect which specific questions landed in each segment more than
genuine retrieval-configuration differences. The dataset-wide average is
the honest reporting unit for this metric at this scale.

### Interpretation guide

Once scores are populated, the interpretation follows this pattern:

- **Recall@5: Semantic → Hybrid jump** — BM25 contribution on control ID queries
- **Recall@5: Hybrid → Hybrid+Rerank jump** — Cohere contribution, especially on
  cross-corpus queries where initial ranking is noisiest
- **MRR: Semantic → Hybrid vs Hybrid → Hybrid+Rerank** — which layer drives rank position
- **Governance rows** — if Hybrid ≈ Semantic here, confirms BM25 has no signal on
  abstract governance language (expected from DL-020 analysis)

---

## Execution order

```bash
# Prerequisites: RDS running, PYTHONPATH=., venv active

# One-time labeling — generates relevant_chunk_ids in golden_dataset.json
python evaluation/label_chunks.py

# Retrieval diagnostics — reads labeled dataset, runs 3 configs, outputs table
python evaluation/retrieval_diagnostics.py

# RAGAs evaluation (already run — scores locked)
# python evaluation/ragas_eval.py
```

---

## References

- DL-008 — Hybrid retrieval architecture (dense + BM25 + RRF)
- DL-009 — RAGAs evaluation design and golden dataset
- DL-019 — BM25 sparse query preprocessing
- DL-020 — RAGAs results analysis and failure modes
- DL-021 — This document registered as standalone evaluation reference
- DL-028 — Answer Correctness deliberately excluded from evaluation
