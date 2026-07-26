# 3 — RAGAS evaluation

Adapted from two complementary upstream repositories:

- [`llama-stack-provider-ragas`](https://github.com/Sheryl-shiyi/llama-stack-provider-ragas)
  (a fork of TrustyAI's) — RAGAS as an **out-of-tree llama-stack eval provider**
- [`proj-poc-RAGAS`](https://github.com/Sheryl-shiyi/proj-poc-RAGAS) — the
  **experiment methodology**: 182 Slovak QA pairs, four models compared, one
  judge model scoring all runs

They are not alternatives: the PoC's own architecture diagram runs "Llama Stack +
RAGAS inline", i.e. this very provider. The provider is the engine, the PoC is
the harness.

Prerequisite: the stack from [SETUP.md](SETUP.md). Defects hit here are in
[BUGS.md](BUGS.md).

---

## 3.1 Matching the original PoC

Its presentation documents the setup precisely, and we match it:

| Parameter | Upstream PoC | Here |
|-----------|--------------|------|
| Embedding | Qwen3-4B, dim 2560 | `ollama/qwen3-embedding:4b-fp16`, dim 2560 |
| Chunking | 512 tokens, overlap 64 | same |
| Judge | Gemma-3-27B (LLM-as-judge) | `ollama/gemma3:27b-it-fp16` |
| Framework | RAGAS, inline mode | TrustyAI provider, inline |
| Dataset | 182 QA pairs from the *Peňaženka zdravia* FAQ | same, with their `reference` answers |
| Vector store | PGVector | FAISS (local) |
| Serving | vLLM on OpenShift AI | Ollama on the host |

Their repository ships the derived QA pairs but **not** the source PDFs, so the
corpus (16 VšZP PDFs) is supplied locally in `docs/vszp/data` and ingested into a
single `vszp` store.

Retrieval on Slovak is near-exact after the embedding switch — for the first eval
question the top chunk is the FAQ entry that answers it, matching the reference
text almost word for word.

---

## 3.2 The provider

Provider **0.7.0** is the release that targets llama-stack **0.6.x**, so it lines
up with our image exactly (its `main` branch is in maintenance mode; 0.7.0 is
final). It is installed in `Containerfile-0.6.0` and wired in
`config-0.6.0.yaml`:

```yaml
apis: [..., eval, benchmarks, datasetio]
providers:
  eval:
  - provider_id: ${env.EMBEDDING_MODEL:+trustyai_ragas_inline}
    provider_type: inline::trustyai_ragas
    module: llama_stack_provider_ragas.inline      # external provider
```

The provider is gated on `EMBEDDING_MODEL` (set in
`compose-model-override.yml`), which is also the embedding model the
similarity-based metrics use — it cannot be set per benchmark.

The `remote` flavour of the provider needs a Kubeflow Pipelines server and is
not used. Only `localfs` datasetio is wired, since our eval data is local.

Confirm it is live:

```bash
curl -s http://localhost:8321/v1/providers | grep -o '"trustyai_ragas_inline"'
```

---

## 3.3 The harness

Two steps, mirroring the PoC's notebooks:

```bash
# 1. questions -> RAG -> {user_input, response, retrieved_contexts, reference}
.client06-venv/bin/python rag-eval/run_rag.py ollama/gemma3:27b-it-fp16 [LIMIT]

# 2. those rows -> dataset + benchmark -> run_eval with a judge model
.client06-venv/bin/python rag-eval/score_ragas.py \
    rag-eval/results/eval_data__ollama_gemma3_27b-it-fp16.json \
    ollama/gemma3:27b-it-fp16 [LIMIT]
```

`run_rag.py` takes any registered model id, so prefixing with `nemo/` measures
the guardrailed path instead of the direct one. `reference` (ground truth) always
comes from the upstream PoC's dataset, keeping our numbers comparable to theirs.

Outputs land in `rag-eval/results/` (gitignored — generated, and derived from the
internal documents).

### Metrics

All six of the PoC's metrics, once the provider is patched:

```
faithfulness · answer_relevancy · context_precision · context_recall
answer_similarity · factual_correctness
```

`answer_correctness` no longer exists in ragas 0.4.x; `factual_correctness` is
its successor and needed a provider fix to work at all — ragas keys ModeMetric
scores as `factual_correctness(mode=f1)` while the provider looked them up by
the bare name (see [BUGS.md](BUGS.md)). Override the set with `METRICS=a,b,c`.

---

## 3.4 Cost

Measured: **~15–17 s per (row, metric)** for scoring, and ~7 s per question for
generation.

| Scope | Wall clock |
|-------|-----------|
| generation, 182 questions, one model | ~21 min |
| scoring, 182 rows × 6 metrics, one model | ~5 h |
| **full run, one model** | **~5.3 h** |
| full run, three models | **~16 h** |
| 40-question subset, three models | ~3.5 h |

The judge and the model under test are usually different, so Ollama swaps them
once per model (~30 s). The embedding model (8 GB) stays resident alongside the
LLM without thrashing.

---

## 3.5 Smoke-test result

Two rows, gemma3 generating and judging, to prove the pipeline end to end:

| Metric | Aggregate |
|--------|-----------|
| faithfulness | 1.000 |
| context_precision | 1.000 |
| context_recall | 1.000 |
| answer_similarity | 0.975 |
| answer_relevancy | 0.673 |
| factual_correctness | 0.665 |

Two rows prove nothing about quality — they prove the wiring. The high
context scores are consistent with the near-exact retrieval noted above; the
lower `answer_relevancy` is expected to move most once a real sample is run.

**A full benchmark has not been run yet** — the scope decision (which models, how
many questions) is open.

---

## 3.6 Before trusting the numbers

Read [EVALUATION-LIMITS.md](EVALUATION-LIMITS.md). The short version, all
measured on this stack:

- Only **four** of the six metrics can separate the models; two of them never see
  the answer and measure the shared retrieval layer instead.
- 99 % of the questions **and** their reference answers appear verbatim in a PDF
  that is in the corpus, so this is closer to a retrieval-and-copy task than a
  reasoning benchmark.
- `answer_similarity` scores a **negated fact** or a **10× wrong euro amount** at
  ~0.99, while a **fully correct answer in English** scores 0.83 — it is a
  fluency-and-topic check, not a correctness check.
- **No metric measures Slovak language quality**, so a fluent-Czech or
  broken-Slovak answer would pass unflagged.
