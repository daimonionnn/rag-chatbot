# 4 — What this evaluation does *not* measure

A critique of the RAGAS setup in [EVALUATION.md](EVALUATION.md): where the numbers
are trustworthy, where they are misleading, and what to change.

Two labels are used throughout, and the distinction matters:

- **MEASURED** — verified on this stack, with the figures shown.
- **REASONED** — an argument from how the metrics are built, not yet tested.

Written while the first full benchmark was still running, so the specific scores
are not in yet. **Revisit once all three models are done** — §4.9 lists what to
re-check against real data.

---

## 4.1 Only four of the six metrics can separate the models

**MEASURED.** The inputs each metric actually consumes:

| Metric | Uses `response`? | Inputs |
|--------|------------------|--------|
| `faithfulness` | yes | response, retrieved_contexts, user_input |
| `answer_relevancy` | yes | response, user_input |
| `answer_similarity` | yes | reference, response |
| `factual_correctness` | yes | reference, response |
| `context_precision` | **no** | reference, retrieved_contexts, user_input |
| `context_recall` | **no** | reference, retrieved_contexts, user_input |

`context_precision` and `context_recall` never see the answer. Retrieval is
identical for every model here — same vector store, same embedding, same
top-5 — so those two measure **the retrieval layer, not the model**, and will
come out essentially the same for all three.

**Fix:** report them once, as a property of the retrieval configuration, not as a
per-model column. Otherwise a table of six metrics implies six independent
comparisons when there are four.

---

## 4.2 The benchmark is a retrieval-and-copy task, not a reasoning task

**MEASURED.** Of the 182 QA pairs, checked against the FAQ PDF that is *in* the
ingested corpus:

```
questions found verbatim in the FAQ PDF : 180 (99%)
reference answers found verbatim        : 180 (99%)
```

The ground-truth answer is literally present in the text the retriever fetches.
So high scores are the expected outcome of a working pipeline, not evidence of
strong reasoning — and a model with better reasoning has almost nothing to
demonstrate. This also explains the near-perfect early figures (faithfulness
1.000, context_recall 1.000, lexical overlap against reference median 1.00).

**Consequences**

- The suite cannot rank models on reasoning, synthesis or handling conflicting
  sources, because none of that is exercised.
- `context_recall ≈ 1.0` says the FAQ chunk was retrieved. It says nothing about
  retrieval quality on questions phrased unlike the FAQ.
- Real users will not phrase questions the way the FAQ does.

**Fix:** add (a) paraphrased questions, (b) questions whose answer spans several
documents, (c) questions answerable only from *other* documents in the corpus
(`Program Vernosť+`), and (d) unanswerable questions, to measure abstention.

---

## 4.3 `answer_similarity` is nearly blind to facts — measured

**MEASURED.** `answer_similarity` is a cosine similarity between embeddings of
the answer and the reference. Perturbing a real reference answer and scoring each
variant against the original:

| Variant of the reference answer | Score | Penalty |
|---------------------------------|-------|---------|
| identical | 1.0000 | — |
| small grammar errors (wrong case endings) | 0.9985 | 0.0015 |
| **`30 eur` → `300 eur`** (10× wrong amount) | **0.9899** | 0.010 |
| **negated** (`Nie je spoplatnená` → `Je spoplatnená`) | **0.9943** | 0.006 |
| **negated** (`môžete` → `nemôžete`) | 0.9636 | 0.036 |
| `raz za rok` → `raz za mesiac` | 0.9547 | 0.045 |
| grossly wrong content (wrong place entirely) | 0.7856 | 0.214 |
| **correct answer, but written in English** | **0.8293** | 0.171 |

Read the two bold rows together:

> An answer stating the **opposite** of the truth, or a **ten-times-wrong euro
> amount**, scores **0.99**. A **fully correct** answer written in English scores
> **0.83**.

So on this metric alone, fluent Slovak nonsense outranks a correct answer in the
wrong language by a wide margin. This is a well-known property of embedding
similarity — negation and numbers are weakly represented — not a bug in this
setup, but it decides how the numbers must be read:

**`answer_similarity` is a fluency-and-topic check, not a correctness check.**
The factual burden rests entirely on `factual_correctness` (claim decomposition)
and `faithfulness` (statement-level grounding). If those two disagree with
`answer_similarity`, believe them, not it.

**Fix:** stop treating `answer_similarity` as a quality headline. For a domain
full of amounts, limits and eligibility conditions, add a targeted check:
extract numbers, dates and negations from answer and reference and compare them
exactly. A wrong amount should fail loudly, not cost 0.01.

---

## 4.4 Nothing here measures Slovak at all

This was the question that prompted this document: *how well do these tests tell
whether the model's Slovak is correct, and could a small grammatical slip be
punished harder than a fluent falsehood?*

**MEASURED, and the answer is in two parts.**

**No metric in the suite has language quality as a target.** None scores grammar,
morphology, register or fluency. Slovak correctness is simply not part of the
measurement.

**The specific fear — grammar punished harder than a lie — does not hold, but the
reality is not reassuring either.** From the table in §4.3: grammar errors cost
**0.0015**, a negated fact costs **0.006–0.036**. So the lie is penalised more —
but both are inside the noise. The real distortion is elsewhere:

| Kind of defect | Penalty on `answer_similarity` |
|----------------|-------------------------------|
| broken grammar, correct content | 0.0015 |
| perfect grammar, negated fact | 0.006 |
| perfect grammar, 10× wrong amount | 0.010 |
| **correct content, wrong language** | **0.171** |

The metric reacts ~17× more strongly to *which language you answered in* than to
*whether the answer was true*. And it does that for the wrong reason: not because
it judges language, but because a different language is a different surface form.

Practical consequences for a Slovak-facing product:

- A model answering **fluently in Czech**, or in clumsy but comprehensible
  Slovak, would score well. Nothing flags it.
- A model answering **correctly in English** would be penalised — but as a
  side effect, not by a language rule, and not consistently enough to rely on.
- **Grammatical quality is effectively untested.** For a customer-facing
  assistant that is a real gap, since users judge exactly that.

**Fix — two cheap additions:**

1. **Language ID on the output.** The NeMo image already ships fastText
   (`lid.176.ftz`) for the input rail; run the same check on generated answers
   and report the share that are Slovak. This turns a hidden failure into a
   number. Note the caveat found in [BUGS.md](BUGS.md) B1: fastText silently
   returns "allowed" on any exception, so the check must be asserted, not trusted.
2. **An explicit fluency/grammar score.** A short LLM-graded rubric (grammar,
   morphology, naturalness, 1–5) run over the answers, kept *separate* from the
   RAGAS numbers. It must not be folded into a single quality figure, because
   fluency and factual accuracy trade off differently and should stay visible
   as two axes.

**REASONED caveat on both:** the judge is a general multilingual model, not a
Slovak-native evaluator, and its competence at judging Slovak claims is itself
unvalidated. Every metric that routes through the judge inherits that
uncertainty — including the fluency score just proposed. A sample graded by a
human speaker is the only way to calibrate it.

---

## 4.5 The judge is one of the contestants

**REASONED.** Following the upstream PoC, `gemma3:27b-it-fp16` judges all runs,
including its own answers. LLM-as-judge setups are documented to favour outputs
resembling the judge's own style, so gemma3 has a structural advantage of unknown
size.

**Fix:** cross-judge. Score every model's answers with each of the three judges
and report the matrix. If a model's rank changes with the judge, the ranking is
about the judge, not the model. Scoring one model with one judge costs ~5 h here,
so a full 3×3 matrix is ~45 h — a 40-question subset makes it affordable
(~10 h) and is enough to detect the effect.

---

## 4.6 One run, so small differences mean nothing

**REASONED.** Everything runs once, at `temperature 0`. That reduces variance but
does not remove it: the judge decomposes claims and emits verdicts, and those
paths are not bit-stable. There is no repeat, no seed control and no confidence
interval, so **a one- or two-point gap between models is not interpretable.**

**Fix:** re-score one model's answers 3–5× and treat the spread as the noise
floor. Then only report differences that exceed it. Cheap version: repeat on 40
rows rather than 182.

---

## 4.7 Things not measured at all

| Gap | Why it matters |
|-----|----------------|
| **The guardrailed path** | Only `ollama/*` is evaluated. The `nemo/*` path — the one with the safety rails, and closest to production — is never scored, so the quality and latency cost of the rails is unknown. |
| **Latency, VRAM, throughput** | A 64 GB model that is meaningfully slower for +1 point is a bad production trade, but nothing in the suite sees it. Generation speed and VRAM are known per model (see [SETUP.md](SETUP.md)) and belong in the same table as the scores. |
| **Correct abstention** | When retrieval misses, saying "this is not in the documents" is the right behaviour — one gemma3 answer did exactly that. Against a reference containing real content, `factual_correctness` scores it 0, identically to a confident fabrication. Honest abstention and hallucination are indistinguishable in these numbers. |
| **Retrieval configuration** | `top_k=5`, chunk 512/overlap 64 are fixed at the PoC's values and never varied, so it is unknown whether retrieval is the bottleneck. |
| **`factual_correctness` mode** | Runs at the default `mode=f1`, which balances precision and recall. For this domain, precision (not inventing entitlements) probably matters more than recall, and the mode is worth choosing deliberately. |

---

## 4.8 Improvement backlog, in priority order

1. **Output language ID** on every answer (§4.4). Cheapest, closes the largest
   blind spot for a Slovak product.
2. **Exact-match check for numbers, dates and negations** (§4.3). Turns the
   metric suite's weakest point into a hard signal.
3. **Report retrieval metrics once**, not per model (§4.1). Removes a misleading
   column.
4. **Noise floor** from repeat runs (§4.6). Without it no ranking is defensible.
5. **Add latency + VRAM** to the results table (§4.7). Makes the comparison a
   production decision rather than a leaderboard.
6. **Cross-judge on a 40-question subset** (§4.5). Quantifies the judge bias.
7. **Extend the test set**: paraphrases, multi-document questions, unanswerable
   questions (§4.2). The biggest change, and the one that would make the
   benchmark measure reasoning rather than copying.
8. **Score the `nemo/*` path** (§4.7) to price the guardrails.
9. **Human calibration** on a small sample (§4.4), to check the judge at all.

---

## 4.9 Revisit when the benchmark finishes

Specific things to check against the real scores:

- Do `context_precision` / `context_recall` really come out equal across the
  three models? If not, the retrieval is less deterministic than assumed
  (§4.1).
- Are the differences between models smaller than a few points, as §4.2 predicts?
  If a model wins by a wide margin, the "copy task" reading is incomplete.
- Does `answer_similarity` disagree with `factual_correctness` on any row? Those
  rows are where §4.3 bites, and they are worth reading by hand.
- Did the thinking models emit reasoning inline? `run_rag.py` logs
  `NOTE: stripped inline reasoning from N/182 answers`. If N is large for gemma4
  or qwen3.6, their earlier numbers would have been depressed for a reason that
  has nothing to do with answer quality.
- Does gemma3 win narrowly? Then §4.5 (self-judging) becomes the first thing to
  test, not a footnote.
