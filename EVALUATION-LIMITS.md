# 4 — What this evaluation does *not* measure

A critique of the RAGAS setup in [EVALUATION.md](EVALUATION.md): where the numbers
are trustworthy, where they are misleading, and what to change.

Two labels are used throughout, and the distinction matters:

- **MEASURED** — verified on this stack, with the figures shown.
- **REASONED** — an argument from how the metrics are built, not yet tested.

Sections 4.1–4.8 were written while the first full benchmark was still running,
against a 2-row smoke test. §4.9 was the list of what to re-check once real data
existed. §4.10, added afterward, is that re-check — the results are in and one of
them (duplicate questions with mismatched references) turned out to be the
single most concrete finding in this document.

---

## 4.1 Only four of the six metrics can separate the models

**MEASURED.** The inputs each metric actually consumes:

| Metric                | Uses `response`? | Inputs                                    |
|-----------------------|------------------|-------------------------------------------|
| `faithfulness`        | yes              | response, retrieved_contexts, user_input  |
| `answer_relevancy`    | yes              | response, user_input                      |
| `answer_similarity`   | yes              | reference, response                       |
| `factual_correctness` | yes              | reference, response                       |
| `context_precision`   | **no**           | reference, retrieved_contexts, user_input |
| `context_recall`      | **no**           | reference, retrieved_contexts, user_input |

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

| Variant of the reference answer                       | Score      | Penalty |
|-------------------------------------------------------|------------|---------|
| identical                                             | 1.0000     | —       |
| small grammar errors (wrong case endings)             | 0.9985     | 0.0015  |
| **`30 eur` → `300 eur`** (10× wrong amount)           | **0.9899** | 0.010   |
| **negated** (`Nie je spoplatnená` → `Je spoplatnená`) | **0.9943** | 0.006   |
| **negated** (`môžete` → `nemôžete`)                   | 0.9636     | 0.036   |
| `raz za rok` → `raz za mesiac`                        | 0.9547     | 0.045   |
| grossly wrong content (wrong place entirely)          | 0.7856     | 0.214   |
| **correct answer, but written in English**            | **0.8293** | 0.171   |

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

| Kind of defect                      | Penalty on `answer_similarity` |
|-------------------------------------|--------------------------------|
| broken grammar, correct content     | 0.0015                         |
| perfect grammar, negated fact       | 0.006                          |
| perfect grammar, 10× wrong amount   | 0.010                          |
| **correct content, wrong language** | **0.171**                      |

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

| Gap                            | Why it matters |
|--------------------------------|-----|
| **The guardrailed path**       | Only `ollama/*` is evaluated. The `nemo/*` path — the one with the safety rails, and closest to production — is never scored, so the quality and latency cost of the rails is unknown. |
| **Latency, VRAM, throughput**  | A 64 GB model that is meaningfully slower for +1 point is a bad production trade, but nothing in the suite sees it. Generation speed and VRAM are known per model (see [SETUP.md](SETUP.md)) and belong in the same table as the scores. |
| **Correct abstention**         | When retrieval misses, saying "this is not in the documents" is the right behaviour — one gemma3 answer did exactly that. Against a reference containing real content, `factual_correctness` scores it 0, identically to a confident fabrication. Honest abstention and hallucination are indistinguishable in these numbers. |
| **Retrieval configuration**    | `top_k=5`, chunk 512/overlap 64 are fixed at the PoC's values and never varied, so it is unknown whether retrieval is the bottleneck. |
| **`factual_correctness` mode** | Runs at the default `mode=f1`, which balances precision and recall. For this domain, precision (not inventing entitlements) probably matters more than recall, and the mode is worth choosing deliberately. |

---

## 4.8 Improvement backlog, in priority order

Re-ordered after §4.10 landed a measured result: fixing the dataset now outranks
everything, since it demonstrably moves the numbers more than any model
difference found.

0. **Fix the 23 duplicate/narrow-reference questions** (§4.10.2). Measured to
   depress `factual_correctness` by more than any model-to-model gap in the
   benchmark, for all three models. Nothing else on this list is worth doing
   before this.
1. **Noise floor** from repeat runs (§4.6, §4.10.1). Without it, none of the
   3–5 point model gaps found are defensible as real.
2. **Output language ID** on every answer (§4.4). Cheapest remaining item,
   closes the largest blind spot for a Slovak product.
3. **Exact-match check for numbers, dates and negations** (§4.3). Turns the
   metric suite's weakest point into a hard signal.
4. **Add latency + VRAM** to the results table (§4.7, §4.10.3). gemma4 cost
   4.5× gemma3's generation time for a few points of `faithfulness` — a real
   production trade-off the current table hides entirely.
5. **Report retrieval metrics once**, not per model (§4.1). Removes a
   misleading column — confirmed bit-identical between two of the three models.
6. **Cross-judge on a 40-question subset** (§4.5). gemma3 leads on two of four
   real metrics by exactly the margin self-judging bias could produce.
7. **Extend the test set**: paraphrases, multi-document questions, unanswerable
   questions (§4.2). The biggest change, and the one that would make the
   benchmark measure reasoning rather than copying.
8. **Score the `nemo/*` path** (§4.7) to price the guardrails.
9. **Human calibration** on a small sample (§4.4), to check the judge at all.

---

## 4.9 What was checked, and the answer

- **Do `context_precision` / `context_recall` really come out equal?** Yes.
  `context_recall` was **bit-identical** between gemma3 and gemma4 (0.9960 =
  0.9960); qwen3.6 differed only at the fourth decimal (0.9932). §4.1 confirmed.
- **Are the differences smaller than a few points?** Yes, on the four metrics
  that matter: at most a 5-point gap (`factual_correctness`, gemma3 vs qwen3.6).
  Consistent with §4.2's "retrieval-and-copy task" reading — see §4.10.1 for why
  even that gap is not fully trustworthy.
- **Does `answer_similarity` disagree with `factual_correctness`?** Frequently,
  and by a lot — up to a 0.95-point gap on individual rows. See §4.10.2: the
  worked example is not a metric quirk but a **dataset defect**.
- **Did the thinking models leak reasoning into the answer?** No. `run_rag.py`'s
  `NOTE: stripped inline reasoning` line never printed for any of the 546
  generations (182 × 3 models). See §4.10.3 for what their extra generation time
  means instead.
- **Does gemma3 win narrowly?** Yes, on two of four real metrics, by 3–5 points —
  small enough that §4.5's self-judging concern is live, not a footnote. It was
  not tested further here (would need cross-judging, §4.5's proposed fix).

Full numbers: [EVALUATION.md §3.7](EVALUATION.md).

---

## 4.10 Confirmed against the real benchmark

### 4.10.1 No noise floor exists, and the gaps are within where one might matter

§4.6's concern stands unresolved: with one run per model, there is no measured
distribution to compare a 3–5 point gap against. The gaps found
(`factual_correctness`: gemma3 0.889 vs qwen3.6 0.801; `answer_similarity`:
0.963 vs 0.891) are exactly the size where it matters whether they are signal or
judge noise, and this run cannot tell the two apart. Treat the ranking in
§EVALUATION.md 3.7 as suggestive, not decisive, until repeat runs exist.

### 4.10.2 A dataset defect, not a metric quirk: duplicate questions, mismatched references

The single most concrete finding from the full run. Of the 182 questions,
**23 (46 rows, 25 % of the dataset) are exact-text duplicates** — the same
question appears twice, once scoped to *Peňaženka zdravia MINI* and once to
*MAXI*, each with a reference answer that only states the rule for its own
product:

```
idx 39  (MINI):  reference = "…z Peňaženky zdravia MINI je možné zaslať iba na účty registrované na Slovensku."
idx 123 (MAXI):  reference = "…z Peňaženky zdravia MAXI je možné zaslať iba na účty registrované na Slovensku."
```

Both gemma3 and qwen3.6 answered **both** occurrences identically and completely:
*"Finančné príspevky z Peňaženky zdravia MINI a MAXI je možné zaslať iba na účty
registrované na Slovensku."* This is not a hallucination — the retrieved context
literally contains the MAXI-specific FAQ entry confirming the same rule, so the
answer is fully grounded. `faithfulness` scored it **1.0 in all four
combinations** (2 models × 2 indices), correctly recognising the grounding.

`factual_correctness` scored the *same answer text* **1.0 at idx 39 and 0.0 at
idx 123**, for both models. Its claim-matching is bidirectional against the
*reference*, not the corpus: at idx 123 the answer's "MINI" claim cannot be
verified against a reference that only ever mentions MAXI, so it is treated as
unsupported, and the correct, grounded answer scores zero.

This is not an isolated case. Averaged over all three models, `factual_correctness`
on the 46 duplicate-question rows is measurably lower than on the 136 unique ones:

| Model   | duplicate-question rows | unique-question rows | gap    |
|---------|------------------------:|---------------------:|-------:|
| gemma3  | 0.831                   | 0.908                | −0.077 |
| gemma4  | 0.818                   | 0.853                | −0.035 |
| qwen3.6 | 0.781                   | 0.807                | −0.026 |

Every model loses more on the flawed 25 % of the dataset than the actual
model-to-model gaps in §EVALUATION.md 3.7 (3–5 points). **The single biggest lever
on these numbers is not the model, the judge, or the metric — it is fixing (or
removing) the 23 duplicate/narrow-reference questions**, something no amount of
prompt or model tuning can work around.

**Fix:** either merge each MINI/MAXI pair into one reference that states the rule
generically (it is, after all, the same rule), or drop the narrower half of each
duplicate. Re-run after fixing this before drawing any conclusion from
`factual_correctness`.

### 4.10.3 The thinking models' extra time is latency, not contamination

gemma4 took 76 min to generate 182 answers against gemma3's 17 min (4.5×) and
qwen3.6's 41 min, while producing similarly-sized answers (median 268 vs 248
chars) — not proportionally longer output. Combined with zero `<think>` tags
found in any answer, the extra time is consistent with Ollama executing (and
billing for) reasoning tokens that never reach the `content` field, rather than
visible reasoning contaminating the scored text. Good news for the fairness of
the comparison; bad news for anyone budgeting latency — §4.7's proposed
latency/VRAM column in the results table would have caught this immediately and
is still not there.

### 4.10.4 Answer length tracks distance from the reference

Median answer length rises monotonically with the metrics that measure closeness
to the reference: gemma3 (248 chars) scores highest on `answer_similarity` /
`factual_correctness`; qwen3.6 (355 chars) scores highest on `answer_relevancy`
and lowest on the reference-matching metrics. Consistent with §4.2 and §4.3:
longer, more elaborated (and plausibly more genuinely helpful) answers diverge
lexically from a terse FAQ-style reference even when equally well-grounded. This
is the same mechanism as §4.10.2, operating continuously rather than as a binary
dataset defect — another reason `answer_similarity` and `factual_correctness`
should not be read as the final word on quality without the fluency/relevancy
metrics alongside them.
