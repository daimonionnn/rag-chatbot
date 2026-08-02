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

---

## 3.9 Which model, and how far the ranking can be trusted

§3.7 and §3.8 measured five configurations. Collected here on one scale, with the
0.006 noise floor from §3.8 applied, so gaps that are not real are not read as
rankings.

| Configuration    | faithfulness | answer_relevancy | answer_similarity | factual_correctness | median chars | generation |
|------------------|-------------:|-----------------:|------------------:|--------------------:|-------------:|-----------:|
| **gemma3**       | 0.9820       | 0.6030           | **0.9628**        | **0.8885**          | 248          | 17 min     |
| gemma4 think     | 0.9872       | 0.6507           | 0.9242            | 0.8438              | 268          | 76 min     |
| gemma4 no-think  | **0.9874**   | 0.6381           | 0.9223            | 0.8361              | 247          | 22 min     |
| qwen3.6 think    | 0.9713       | **0.6634**       | 0.8914            | 0.8008              | 355          | 41 min     |
| qwen3.6 no-think | 0.9740       | 0.6413           | 0.9086            | 0.8351              | 294          | **11 min** |

`faithfulness` does not separate gemma3 from gemma4 — 0.9820 vs 0.9874 is inside
the noise floor. The other three have a clear winner each.

**Ranking on this corpus: gemma3, then gemma4, then qwen3.6.** gemma3 takes two of
the four metrics by margins far outside the noise (+0.039 `answer_similarity`,
+0.045 `factual_correctness` over the next best); gemma4 takes `faithfulness` but
only within noise of gemma3; qwen3.6 takes `answer_relevancy` and is last on
matching the reference.

### It is not a length artifact

§3.8 showed shorter answers score higher on the reference-matching metrics, which
would be an obvious way to explain gemma3's lead away. It does not survive the
data. gemma3 (248 median chars) and gemma4 no-think (247) are the same length and
still differ by **0.040** on `answer_similarity` and **0.052** on
`factual_correctness`. The length effect is real *within* a model and does not
account for the gaps *between* them.

### The confound that does bite

**gemma3 is the judge** (§4.5), and the metric it wins most decisively,
`factual_correctness`, is judge-scored. A judge preferring answers that look like
its own output is the textbook shape of this, and nothing in these runs can rule
it out.

The partial counter-evidence: `answer_similarity` has **no judge in the loop** —
it is cosine similarity between embeddings — and gemma3 leads there too, at
identical answer length. So gemma3 genuinely produces text closest to the
reference, judge or no judge. But `answer_similarity` is the metric §4.3 measured
as nearly blind to correctness (0.9943 for a negated fact), so "closest to the
reference" is not "most correct", and the metric that would settle it is the
confounded one.

**Settled in §3.10** by re-scoring every model's existing answers with a judge
that is not one of the contestants. gemma3's first place survives; the second and
third places do not.

### Practical recommendation

- **gemma3 as the default** for this corpus: it wins reference-matching, generates
  fastest among the non-thinking options, and is the PoC's original choice.
- **gemma3 cannot do tool calling at all** (BUGS.md B3), so if Agent-based mode is
  wanted it is out, and **qwen3.6 with thinking off** is the pick — fastest of all
  five at 11 min, and `factual_correctness` 0.8351 rather than 0.8008.
- **Do not enable thinking on either model.** It buys nothing measurable on gemma4
  for 3.5× the generation time, and on qwen3.6 it actively costs factual accuracy.

---

## 3.10 Cross-judged: which parts of the ranking are about the models

§3.9 ranked five configurations, and [EVALUATION-LIMITS.md §4.5](EVALUATION-LIMITS.md)
objected that the judge was one of the contestants: gemma3 scored every run,
including its own, and the metric it won most decisively — `factual_correctness`
— is judge-scored. This section re-scores the same answers with a judge that is
in no way a contestant, `anthropic/claude-opus-5`, and reports what moved.

Nothing was regenerated. The stored answers and their retrieved contexts are read
verbatim, so **the judge is the only thing that differs** from §3.7. Ran
2026-08-01, 40 rows per model, zero failed judge calls.

| Configuration    | Wall clock | Cost       |
|------------------|-----------:|-----------:|
| gemma3           | 62.3 min   | $10.86     |
| gemma4           | 59.0 min   | $10.91     |
| qwen3.6          | 66.8 min   | $12.09     |
| 2-row smoke test | 2.5 min    | $0.50      |
| **total**        | **~3.2 h** | **$34.36** |

**Cost scales with the length of the answers being judged, not with the row
count.** qwen3.6's answers are 47 % longer than gemma3's in this subset (17,971
vs 12,203 characters) against byte-identical contexts, and it cost 11 % more and
took 13 % longer. Solving the two for a fixed and a length-proportional part puts
roughly **76 % of the bill on the retrieved contexts and 24 % on the answers** —
the contexts are the same for every model and dominate, while answer length moves
the total by about a quarter of its own proportional change. The same split
predicts gemma4 (answers 1.002× gemma3's) at $10.87 against $10.91 actual.

Budget a cross-judge run from the answer lengths, then, not from the question
count — and note this is also why the cheapest model to judge is the tersest one,
which is a property of the model under test rather than of the judge.

### The subset, and why it is not 40 random rows

§4.10.2 measured that the 46 rows whose question text is duplicated (the MINI /
MAXI pairs) score lower on `factual_correctness` than the 136 unique ones, for
every model. A subset that sampled them at a different rate would not be
comparable to the full run, so `rag-eval/make_subset.py` preserves the
proportion — 25.0 % against the full set's 25.3 % — and takes **whole pairs
only**, since §4.10.2's effect is that the *same answer* scores 1.0 at one index
of a pair and 0.0 at the other. Both judges score the same 40 indices, and the
stored 182-row results are sliced to those indices before any comparison, so
changing the judge is never confounded with changing the sample.

### Results

Paired over rows both judges scored (`n` varies by metric because either judge
can fail to score a row — in practice only gemma3 did, on 2 rows of
`faithfulness` and 1 of `factual_correctness`; claude-opus-5 returned a score for
all 40 rows of all 6 metrics on all 3 models). `context_precision` and `context_recall` are omitted
here and discussed below; they never see the answer and so cannot rank models.

| Metric              | gemma3          | gemma4     | qwen3.6    | gemma3                 | gemma4     | qwen3.6    | n   |
|---------------------|----------------:|-----------:|-----------:|-----------------------:|-----------:|-----------:|----:|
|                     | *judge: gemma3* |            |            | *judge: claude-opus-5* |            |            |     |
| faithfulness        | 0.9794          | **0.9846** | 0.9598     | 0.9971                 | **1.0000** | 0.9732     | 38  |
| answer_relevancy    | 0.5896          | 0.6498     | **0.6791** | 0.7173                 | 0.7920     | **0.8073** | 40  |
| answer_similarity   | **0.9564**      | 0.9160     | 0.8759     | **0.9564**             | 0.9160     | 0.8759     | 40  |
| factual_correctness | **0.9023**      | 0.8369     | 0.7733     | **0.8810**             | 0.7718     | 0.7679     | 39  |

**Every metric's winner is unchanged.** All four pick the same model under both
judges.

### gemma3's first place is not an artefact of self-judging

The concern was specifically that gemma3 inflates its own `factual_correctness`.
It does not — or rather, whatever it does to its own score it does more to
gemma4's:

| `factual_correctness` | judge gemma3 | judge claude-opus-5 |
|-----------------------|-------------:|--------------------:|
| gemma3 − gemma4       | +0.0654      | **+0.1092**         |
| gemma3 − qwen3.6      | +0.1290      | +0.1131             |

The lead over gemma4 nearly doubles under a neutral judge and the lead over
qwen3.6 holds (the −0.016 change is inside the noise floor below). §4.5's
hypothesis pointed the right way at the wrong target: the confound was real, but
it was *understating* gemma3's margin, not manufacturing it.

### Second place: the margin moves, the order does not

| `factual_correctness` | judge gemma3 | judge claude-opus-5 |
|-----------------------|-------------:|--------------------:|
| gemma4 − qwen3.6      | +0.0636      | **+0.0039**         |

Under this judge the two are indistinguishable — 0.0039 is a sixth of the
sample's resolution — where gemma3 separated them by six points. On two judges
that reads as second place being the judge's opinion rather than a property of
the answers.

**It does not survive a third judge.** §3.11 completes the matrix and finds the
same pair separated by +0.0995 under qwen3.6 — so across three judges the margin
ranges from a tie to ten points while the *order* never reverses. The claim this
section originally made, that second place was an artefact, was one judge's
result generalised too far; see §3.11 for the corrected reading.

### Metric levels are judge-dependent; rankings are not

`answer_relevancy` rose by +0.128 to +0.142 for **all three** models while
preserving their order. Its absolute value therefore says almost nothing on its
own — a 0.72 from one judge and a 0.59 from another describe the same answers.
Read it only as a within-judge comparison. This is not visible anywhere in §3.7's
table, which presents the figure as if it were a property of the model.

`answer_similarity` reproduces to four decimals across judges, as it must: it is
cosine similarity between embeddings with no judge in the loop. That it came out
identical is the control that gives the rest of the table its weight — it
confirms both judges saw the same rows, sliced the same way.

### A second noise floor, again for free

`context_precision` and `context_recall` consume reference, contexts and question
— never the answer. Across the three model files those inputs are
**byte-identical**, so three scorings should return one value each. They return
two, on both metrics. §3.8 used exactly this to derive its 0.006 floor:

| Scored on      | context_precision | context_recall |
|----------------|------------------:|---------------:|
| gemma3's file  | 0.8983            | **0.9679**     |
| gemma4's file  | 0.8983            | 0.9929         |
| qwen3.6's file | **0.8995**        | 0.9929         |

In each case exactly **one row out of 40** flipped — `context_precision` on the
qwen3.6 file, `context_recall` on the gemma3 file. gemma3-as-judge is no better
behaved: it split 0.9914 / 0.9815 on `context_precision` between two files while
reproducing `context_recall` exactly.

That sets this sample's resolution: one row is 0.025, so no difference below that
is interpretable, and the floor is necessarily wider than §3.8's 0.006 because
the sample is a quarter the size.

Applying it: gemma3's own `factual_correctness` drop of −0.0202 is *below* the
floor and means nothing on its own; gemma4's −0.0651 and the +0.0438 widening of
the gemma3–gemma4 gap are above it.

It also shows the retrieval metrics are not the clean per-configuration constants
§4.1 assumed. Beyond each judge's own instability above, the two judges disagree
with each other by −0.093 on `context_precision` for identical retrieval. They
measure retrieval *and* judge, and §4.1's fix — report them once, as a property
of the retrieval configuration — is only valid within a single judge.

### What this run cannot separate

The neutral judge is reached over chat completions, while the local judges use
the raw text-completions endpoint that Anthropic does not serve (BUGS.md A4).
Chat applies the model's chat template, so "different judge" and "different
prompt framing" moved together here and no part of the deltas can be attributed
to one rather than the other. Routing the local judges through chat as well would
have made them comparable to each other but invalidated every number in §3.7, so
the confound is documented rather than removed.

Two further limits: 40 rows rather than 182, with the resolution consequence
above; and one judge rather than a full 3×3 matrix, so this says gemma3's lead
survives *this* neutral judge, not every judge.

---

## 3.11 The full 3×3 judge matrix

§3.10 answered §4.5's question with one neutral judge. This completes the matrix
with the third — qwen3.6 scoring all three models, including its own answers —
and the third judge both settles the self-preference question and corrects a
claim §3.10 made on one judge's evidence.

Ran 2026-08-01 → 2026-08-02, 40 rows per model, 368 / 372 / 386 min per run,
**0 of 240 rows unscored in every run**. Getting a thinking model to judge at all
took two fixes (BUGS.md A5); before them it silently dropped rows.

### `factual_correctness` — the metric the whole question is about

| Judge →       | gemma3 | gemma4 | qwen3.6    | Winner |
|---------------|-------:|-------:|-----------:|--------|
| gemma3        | 0.9023 | 0.8369 | 0.7733     | gemma3 |
| claude-opus-5 | 0.8828 | 0.7775 | 0.7728     | gemma3 |
| qwen3.6       | 0.8467 | 0.7183 | **0.6188** | gemma3 |

**gemma3 wins under all three judges**, including under the two that are its
competitors. That is as settled as this benchmark can make it.

### qwen3.6 does not favour itself — it is harshest on itself

The bolded 0.6188 is the lowest figure in the matrix, and qwen3.6 awarded it to
its own answers. Measuring each judge's strictness against the neutral one:

| Judged model         | qwen3.6's score − claude's |
|----------------------|---------------------------:|
| gemma3               | −0.036                     |
| gemma4               | −0.059                     |
| **qwen3.6 (itself)** | **−0.154**                 |

qwen3.6 marks everything down, and marks *itself* down three times harder than it
marks its rivals. Whatever this judge is doing, self-preference is not it.

That also disposes of the residual suspicion about gemma3. gemma3 scores itself
+0.0195 above the neutral judge — **below this sample's 0.025 resolution**. Across
three judges there is no measurable self-preference from either model that judged
its own work. §4.5's mechanism is real in the literature; it is not detectable
here.

### What is unanimous, and what is not

| Metric              | gemma3 judge | claude judge | qwen3.6 judge | Robust?                |
|---------------------|--------------|--------------|---------------|------------------------|
| factual_correctness | gemma3       | gemma3       | gemma3        | yes                    |
| answer_similarity   | gemma3       | gemma3       | gemma3        | yes (no judge in loop) |
| answer_relevancy    | qwen3.6      | qwen3.6      | qwen3.6       | yes                    |
| faithfulness        | gemma4       | gemma4       | **gemma3**    | **no**                 |

`faithfulness` is the only metric whose winner changes with the judge — gemma4
takes it under two judges, gemma3 under the third (0.9875 vs 0.9599). §3.9 had
already noted gemma4's `faithfulness` win sat inside the noise floor against
gemma3; a judge that reverses it confirms that reading. Treat "gemma4 is the most
faithful" as unsupported.

`answer_similarity` is **identical to four decimals under all three judges**, as
it must be — cosine similarity between embeddings, no judge in the loop. Three
independent scorings agreeing exactly is the control that makes the rest of this
table trustworthy.

### The corrected reading of second place

| `factual_correctness` | gemma3 judge | claude judge | qwen3.6 judge |
|-----------------------|-------------:|-------------:|--------------:|
| gemma4 − qwen3.6      | +0.0636      | +0.0047      | +0.0995       |

§3.10 saw the middle column and concluded second place was an artefact of the
judge. With the third column that is wrong: the margin ranges from a tie to ten
points, but **the order never reverses**. claude-opus-5 is the outlier here, not
the arbiter — the lesson being that one neutral judge measures one judge's
opinion, which is the same trap §4.5 identified, one level up.

**So the ranking on `factual_correctness` — gemma3, gemma4, qwen3.6 — is
unanimous across three judges. What is judge-dependent is how far apart they are,
and that varies by a factor of twenty.**

### What this still does not settle

Three judges are not a random sample of judges, and two of the three are
contestants. Answer length remains confounded with model identity (§4.10.4), the
subset is 40 rows with a 0.025 resolution, and the neutral judge is prompted over
a different endpoint than the local two (BUGS.md A4). None of that is fixed by
adding a third column; it is fixed by a better dataset (§4.2, §4.10.2).
