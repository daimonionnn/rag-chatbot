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

| Parameter    | Upstream PoC                                  | Here                                       |
|--------------|-----------------------------------------------|--------------------------------------------|
| Embedding    | Qwen3-4B, dim 2560                            | `ollama/qwen3-embedding:4b-fp16`, dim 2560 |
| Chunking     | 512 tokens, overlap 64                        | same                                       |
| Judge        | Gemma-3-27B (LLM-as-judge)                    | `ollama/gemma3:27b-it-fp16`                |
| Framework    | RAGAS, inline mode                            | TrustyAI provider, inline                  |
| Dataset      | 182 QA pairs from the *Peňaženka zdravia* FAQ | same, with their `reference` answers       |
| Vector store | PGVector                                      | FAISS (local)                              |
| Serving      | vLLM on OpenShift AI                          | Ollama on the host                         |

Their repository ships the derived QA pairs but **not** the source PDFs, so the
corpus (16 VšZP PDFs) is supplied locally in `docs/data/vszp` and ingested into a
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

| Scope                                    | Wall clock |
|------------------------------------------|------------|
| generation, 182 questions, one model     | ~21 min    |
| scoring, 182 rows × 6 metrics, one model | ~5 h       |
| **full run, one model**                  | **~5.3 h** |
| full run, three models                   | **~16 h**  |
| 40-question subset, three models         | ~3.5 h     |

The judge and the model under test are usually different, so Ollama swaps them
once per model (~30 s). The embedding model (8 GB) stays resident alongside the
LLM without thrashing.

---

## 3.5 Smoke-test result

Two rows, gemma3 generating and judging, to prove the pipeline end to end before
committing to the ~16 h full run:

| Metric              | Aggregate |
|---------------------|-----------|
| faithfulness        | 1.000     |
| context_precision   | 1.000     |
| context_recall      | 1.000     |
| answer_similarity   | 0.975     |
| answer_relevancy    | 0.673     |
| factual_correctness | 0.665     |

Two rows prove nothing about quality — they prove the wiring.

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

---

## 3.7 Full-benchmark results

All 182 questions, all three models, judge `ollama/gemma3:27b-it-fp16` throughout
(so the "judge is one of the contestants" caveat in
[EVALUATION-LIMITS.md §4.5](EVALUATION-LIMITS.md) applies to every gemma3 column).
Ran 2026-07-25 21:56 → 2026-07-26 16:57, elapsed 1141 min (~19 h — longer than the
~16 h estimate; see the timing table below for why). Zero job failures; NaN rows
(from a judge reply ragas could not parse, see [BUGS.md](BUGS.md) A2) were scored
as missing and excluded from the means below rather than zeroing the average.

| Metric              | gemma3     | gemma4     | qwen3.6    | Separates models?             |
|---------------------|-----------:|-----------:|-----------:|:-----------------------------:|
| context_recall      | 0.9960     | 0.9960     | 0.9932     | no — retrieval-only, see §4.1 |
| context_precision   | 0.9882     | 0.9844     | 0.9851     | no — retrieval-only, see §4.1 |
| faithfulness        | 0.9820     | **0.9872** | 0.9713     | yes                           |
| answer_relevancy    | 0.6030     | 0.6507     | **0.6634** | yes                           |
| answer_similarity   | **0.9628** | 0.9242     | 0.8914     | yes                           |
| factual_correctness | **0.8885** | 0.8438     | 0.8008     | yes                           |

`context_recall` came out **bit-identical** between gemma3 and gemma4 (0.9960 =
0.9960), confirming §4.1's prediction directly: with retrieval held constant, that
metric cannot distinguish models.

### Generation and data quality

|                                                     | gemma3 | gemma4 | qwen3.6 |
|-----------------------------------------------------|-------:|-------:|--------:|
| generation time (182 q)                             | 17 min | 76 min | 41 min  |
| answer length, median chars                         | 248    | 268    | 355     |
| answer length, max chars                            | 820    | 1977   | 1919    |
| `<think>`/`<reasoning>` tags leaked into the answer | 0      | 0      | 0       |
| faithfulness NaN rows                               | 2      | 3      | 2       |
| factual_correctness NaN rows                        | 1      | 5      | 0       |

gemma4 and qwen3.6 both advertise a `thinking` capability; gemma3 does not.
Despite that, **no reasoning text leaked into any answer** for any model — the
`strip_reasoning()` safeguard in `run_rag.py` never had to trigger (its log line
never printed). gemma4's 4.5× longer generation time with barely longer output is
consistent with Ollama returning reasoning tokens out-of-band rather than in
`content`, so the extra time is a latency cost, not a contamination risk.

### Reading the four real metrics together

- **gemma3** leads on `answer_similarity` and `factual_correctness` — closest to
  the reference text.
- **qwen3.6** leads on `answer_relevancy`, gemma4 close behind; both ahead of
  gemma3.
- **gemma4** leads on `faithfulness`.
- Answer length increases monotonically with the gap from the reference
  (gemma3 248 chars → gemma4 268 → qwen3.6 355), which is the expected shape if
  longer, more elaborated answers diverge lexically from a terse FAQ-style
  reference while still being well-grounded and on-topic.

None of these gaps should be read as a ranking without the caveats in
[EVALUATION-LIMITS.md §4.10](EVALUATION-LIMITS.md) — in particular, a concrete,
measured dataset defect (duplicate questions with mismatched references) was
found to depress `factual_correctness` for all three models, and no repeat runs
exist to establish whether gaps this size exceed the judge's own noise.

---

## 3.8 What thinking is worth

gemma4 and qwen3.6 both reason before answering; gemma3 does not. §3.7 measured
them with reasoning on, which left two things unanswered: how much the reasoning
buys, and — noted there as an open problem — whether gaps that size exceed the
judge's own noise. One experiment settles both.

Every model was re-run with reasoning disabled, against the same judge, the same
questions, and the **same retrieved contexts, reused verbatim** from the
thinking-enabled run (`run_rag.py --no-think`, see BUGS.md D12 for why this has to
bypass the OpenAI-compatible path). The answer is therefore the only thing that
differs between the two columns.

Ran 2026-07-26 22:39 → 2026-07-27 10:46, elapsed 726 min, zero job failures.
`think: false` was confirmed to work rather than assumed: reasoning came back as
exactly **0 characters** across all 364 generations, and in a probe `eval_count`
fell 237 → 24 (gemma4) and 173 → 26 (qwen3.6).

### The noise floor, measured for free

`context_precision` and `context_recall` score *retrieval*, and retrieval was held
byte-identical across the two runs. Whatever they move by is therefore the judge
disagreeing with itself, not an effect:

| Retrieval metric  | gemma4 Δ | qwen3.6 Δ |
|-------------------|---------:|----------:|
| context_precision | −0.0014  | −0.0063   |
| context_recall    | −0.0027  | +0.0000   |

So on this harness **|Δ| up to about 0.006 is noise**. `context_recall` for
qwen3.6 reproduced to the digit (+0.0000), which is the strongest available
evidence that the pipeline itself is stable and the variation is the judge's.

### Results

Paired over the rows both runs scored — the NaN rows are not the same rows in
each run, so means over the full 182 would compare different populations.

| Metric              | gemma4 ON | gemma4 OFF | Δ       | qwen3.6 ON | qwen3.6 OFF | Δ       |
|---------------------|----------:|-----------:|--------:|-----------:|------------:|--------:|
| faithfulness        | 0.9868    | 0.9873     | +0.0005 | 0.9711     | 0.9737      | +0.0025 |
| answer_relevancy    | 0.6507    | 0.6381     | −0.0126 | 0.6634     | 0.6413      | −0.0220 |
| answer_similarity   | 0.9242    | 0.9223     | −0.0019 | 0.8914     | 0.9086      | +0.0172 |
| factual_correctness | 0.8414    | 0.8363     | −0.0051 | 0.8010     | 0.8351      | +0.0341 |

| Generation (182 q) | thinking on | thinking off | speed-up |
|--------------------|------------:|-------------:|---------:|
| gemma4             | 76.5 min    | 22.1 min     | 3.5×     |
| qwen3.6            | 42.3 min    | 11.2 min     | 3.8×     |

| Answer length, median chars | on  | off |
|-----------------------------|----:|----:|
| gemma4                      | 268 | 247 |
| qwen3.6                     | 355 | 294 |

### Reading it

**Thinking is not uniformly better, and for qwen3.6 it is mostly worse.** Turning
it off cost 3.5–3.8× less generation time and moved the metrics like this:

- **`answer_relevancy` drops in both models** (−0.0126, −0.0220) — the only
  consistent cost of removing reasoning, and the only effect that reproduces
  across models.
- **`factual_correctness` for qwen3.6 *rises* by +0.0341** — around five times the
  noise floor, and larger than any gemma4-vs-qwen3.6 gap in §3.7. Reasoning was
  actively hurting factual accuracy for this model on this corpus.
- **`answer_similarity` for qwen3.6 rises by +0.0172.** This metric is
  embedding-only, with no judge in the loop, so it carries no judge noise at all.
- **gemma4 barely moves.** With the 0.006 floor above, only its `answer_relevancy`
  change is real; `faithfulness`, `answer_similarity` and `factual_correctness` are
  all inside the noise.
- **`faithfulness` is inside the noise for both.** Reasoning does not make answers
  more grounded in the retrieved text.

One mechanism plausibly explains every direction at once: **answers get shorter**
without reasoning (qwen3.6 median 355 → 294). Shorter answers sit closer to a
terse FAQ-style reference, which raises `answer_similarity` and
`factual_correctness`, and they cover less ground, which lowers `answer_relevancy`
— exactly the length effect §3.7 already observed *across* models, reproduced here
*within* a model. That makes the qwen3.6 gains a weaker claim than the numbers
suggest on their own, and `answer_similarity` in particular should be read with
[EVALUATION-LIMITS.md §4.3](EVALUATION-LIMITS.md) in hand: it scored a negated
fact 0.9943 and a ten-times-wrong amount 0.9899, so "more similar" is not
"more correct".

The practical read: **for this corpus, reasoning is not worth its cost.** It
triples generation time to buy roughly two points of `answer_relevancy`, and for
qwen3.6 it gives up more `factual_correctness` than it gains anywhere.
