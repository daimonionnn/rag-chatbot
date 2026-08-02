# 5 — Does Slovak hold these models back?

[EVALUATION-LIMITS.md §4.4](EVALUATION-LIMITS.md) measured that the RAGAS suite
scores Slovak **not at all**: no metric targets grammar, morphology, register or
fluency, and a model answering in fluent Czech would pass unflagged. It named two
cheap fixes and left both unbuilt. This is those two, built and run.

It is a separate document rather than a section of [EVALUATION.md](EVALUATION.md)
because it is a different measurement: different corpus, different scoring, and —
for half of it — no judge at all.

---

## 5.1 What is measured, and why in this shape

Two halves, because "is the Slovak good" is two questions that come apart. A
model can understand Slovak perfectly and still write it badly; the reverse is
rarer but the two are not one skill.

| Half                                                 | Question                                                  | Scoring |
|------------------------------------------------------|-----------------------------------------------------------|-----|
| **A** — [`run_belebele.py`](sk-eval/run_belebele.py) | Does the model understand Slovak text and reason over it? | Objective, 4-way multiple choice, **no judge** |
| **B** — [`run_fluency.py`](sk-eval/run_fluency.py)   | Is the Slovak it *produces* correct and natural?          | Orthographic checks (no judge) + a rubric scored by `claude-opus-5` |

### Why Belebele, and why both languages

[Belebele](https://huggingface.co/datasets/facebook/belebele) (Meta,
CC-BY-SA-4.0) is 900 reading-comprehension items over FLORES passages,
**professionally translated** into 122 languages. That is the deciding property:
when the thing being measured is the language, a machine-translated benchmark
measures the translator. The same reasoning ruled out the
[mlmm-evaluation](https://github.com/nlp-uoregon/mlmm-evaluation) Slovak splits
of ARC/HellaSwag/MMLU, which are translated with ChatGPT, and
[skLEP](https://arxiv.org/abs/2506.21508), which is GLUE-style sequence labelling
built for fine-tuned encoders rather than generative models.

The items are parallel across languages, so **the same 100 questions are run in
Slovak and in English**. Slovak accuracy alone conflates "can this model reason"
with "can this model read Slovak". The sk−en difference separates them, with
reasoning ability held constant by construction. A generally weaker model scores
lower in both and shows a small gap; a model weak *at Slovak* shows a large one.

Thinking is left on where supported. This is the one axis where a reasoning model
might earn its cost, and disabling it would decide the question in advance —
unlike [EVALUATION.md §3.8](EVALUATION.md), where thinking bought nothing on a
retrieval-and-copy task.

### Why the prompts in half B look the way they do

Ordinary Slovak prose does not separate these models. The 18 prompts in
[`sk-eval/prompts_sk.json`](sk-eval/prompts_sk.json) target where Slovak actually
breaks: numeral–noun agreement (1 pacient / 2 pacienti / 5 pacientov), genitive
plural, the rhythmic shortening rule, clitic order, verbal aspect, formal
register. The failures below all land there and almost nowhere else, which is
evidence the targeting worked.

The judge is `claude-opus-5` — the neutral one from
[EVALUATION.md §3.10](EVALUATION.md). Using gemma3 or qwen3.6 would put a
contestant in charge of grading its rivals' Slovak, which is §4.5's confound in a
new costume.

---

## 5.2 Half A — comprehension and reasoning

100 items, run 2026-08-02, 0 unparseable replies out of 600.

| Model   | Slovak    | English | **sk − en** | Wall clock |
|---------|----------:|--------:|------------:|-----------:|
| gemma3  | 0.930     | 0.950   | **−0.020**  | **6 min**  |
| gemma4  | 0.940     | 0.970   | −0.030      | 80 min     |
| qwen3.6 | **0.950** | 0.970   | **−0.020**  | 39 min     |

**Slovak is not holding any of these models back.** Every penalty is two or three
items in a hundred. All three read Slovak about as well as they read English, and
§4.4's open question — whether the language is a hidden handicap — is answered
no, for all three.

**The model ranked last by RAGAS understands Slovak best.** qwen3.6 is last in
[EVALUATION.md §3.9](EVALUATION.md) (`factual_correctness` 0.77–0.80) and first
here. The 1–2 item margins are inside noise, so this does not establish that
qwen3.6 comprehends better — but it does rule something out: **its last place is
not caused by weaker Slovak.** What remains is §4.2 and §4.10.4's explanation —
it writes longer, more elaborated answers, and the reference-matching metrics
penalise exactly that.

**Resolution.** 100 items means one item is one point, so model-to-model gaps
under ~5 points are unreadable. That is fine for the question this half was built
for — each model is compared with *itself* across two languages on identical
items — but it means the Slovak column should not be used to rank the models. The
full 900 items would cost eight hours on gemma4 alone.

---

## 5.3 Half B — the Slovak they produce

18 prompts per model, 54 rubric scores, all parsed.

### Orthographic checks (no judge)

| Model   | Czech `ř ě ů` | Answers with no `ô ľ ĺ ŕ ä` | Median diacritic rate | Median length |
|---------|--------------:|----------------------------:|----------------------:|--------------:|
| gemma3  | **0 / 18**    | 5 / 18                      | 0.107                 | 362           |
| gemma4  | **0 / 18**    | 6 / 18                      | 0.112                 | 272           |
| qwen3.6 | **0 / 18**    | 5 / 18                      | 0.109                 | 419           |

### Rubric, 1–5, judged by `claude-opus-5`

| Model   | Grammar  | Naturalness | Task     | Errors listed |
|---------|---------:|------------:|---------:|--------------:|
| gemma3  | **4.28** | 3.78        | 4.17     | 56            |
| gemma4  | 4.22     | **3.94**    | **4.67** | 33            |
| qwen3.6 | 4.17     | 3.83        | 4.39     | 49            |

**Grammar does not separate them.** A 0.11 spread on a five-point scale over 18
prompts is noise. Neither model has a Slovak advantage over the others; gemma4's
lead is on *following the instruction* (4.67), which is a different skill.

**4.2 out of 5 means competent with real errors, not fluent.** A sample the judge
caught, all verified present in the stored answers:

| Model   | Written                 | Correct               | Phenomenon        |
|---------|-------------------------|-----------------------|-------------------|
| gemma3  | filozofi boli **múdry** | múdri                 | agreement         |
| gemma3  | on **mu sa** odvďačil   | on **sa mu** odvďačil | clitic order      |
| gemma4  | až ich bolo **dvojich** | dvaja                 | numeral agreement |
| gemma4  | počet **návštevov**     | návštev               | genitive plural   |
| qwen3.6 | **Této** zimné steny    | **Tieto**             | Czech form        |

The weakest prompts averaged across models were clitic order (3.33), numeral
agreement, prepositional government and rhythmic shortening — the phenomena the
prompts were written to stress.

### The finding that matters most

qwen3.6 wrote **"Této zimné steny"**. `této` is Czech. **The orthographic check
missed it**, because it contains no `ř`, `ě` or `ů` — the check returned an empty
Czech-character list for that very answer.

§4.4 was right to worry about Czech leaking in, and this is what it looks like:
not a Czech-looking sentence, but a single Czech function word inside otherwise
clean Slovak. A character-class check catches only Czech words carrying
exclusive letters; anything spelled from the shared alphabet passes. **The
objective check is necessary and not sufficient** — without the rubric this case
was invisible.

Worth noting where it happened: in the same three-sentence answer, qwen3.6 got
`krásni` and `múdri` right — the rhythmic-shortening forms the prompt was
actually targeting — and failed on the demonstrative instead. Stress prompts
surface errors; they do not surface the errors you predicted.

---

## 5.4 What this does and does not establish

**Established.** Slovak is not a handicap for any of the three, in comprehension
or in production. All three write competent Slovak with real errors, at
indistinguishable rates. None of this was visible in any RAGAS metric, which is
§4.4's point restated with numbers.

**Not established.** Whether one model's Slovak is better than another's — the
margins are inside noise on both halves. Belebele measures comprehension of a
short passage, not knowledge of Slovak realities or law. The rubric is one
judge's opinion of 18 prompts, not calibration against a native speaker, which
§4.4 names as the only real validation and which remains undone. And a
900-character-per-answer test says nothing about a long conversation.

**Cost.** ~2 h GPU end to end (6 / 80 / 39 min for half A, plus generation) and
~$1 of judging. gemma4 spent thirteen times gemma3's wall clock to finish one
item ahead of it — the same trade [EVALUATION.md §3.8](EVALUATION.md) found on
the RAGAS corpus, reproduced on a different task.

---

## 5.5 Reproducing

```bash
python3 sk-eval/fetch_belebele.py 100          # dataset slice, gitignored
python3 sk-eval/run_belebele.py MODEL 100      # half A, per model
python3 sk-eval/run_fluency.py generate MODEL  # half B answers, per model
python3 sk-eval/run_fluency.py judge           # rubric over everything generated
```

Run both halves for one model while it is resident — each is ~50 GB and Ollama
holds one at a time. The judge step needs `ANTHROPIC_API_KEY` and the stack from
[SETUP.md](SETUP.md); everything else is local.
